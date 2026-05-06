import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.distance import geodesic

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖-手動定位版")

# --- 1. 高效率資料匯入與快取 ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    STANDARD_CITIES = [
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
        "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
        "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
        "臺東縣", "澎湖縣", "金門縣", "連江縣"
    ]

    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else "暫無介紹內容。"
                reg_node = info.find('Region')
                add_node = info.find('Add')
                reg_text = reg_node.text.strip() if reg_node is not None and reg_node.text else ""
                add_text = add_node.text.strip() if add_node is not None and add_node.text else ""
                
                geo_combined = (reg_text + add_text).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in geo_combined:
                        found_city = c
                        break
                
                px = info.find('Px').text if info.find('Px') is not None else None
                py = info.find('Py').text if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "緯度": float(py),
                        "經度": float(px),
                        "介紹": desc,
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # 社群回報資料
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
            if '介紹' not in sheet_df.columns:
                sheet_df['介紹'] = "社群推薦親子景點。"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 2. 初始化 Session State (儲存點擊的位置) ---
if 'center_coords' not in st.session_state:
    # 預設位置 (台北車站)
    st.session_state.center_coords = (25.0478, 121.5170)

# --- 3. 介面與篩選邏輯 ---
st.sidebar.header("📍 定位與篩選")
st.sidebar.info("💡 **手動定位**：在右側地圖上**任意位置點擊一下**，紅色的中心標記就會跳轉到該處，並重新計算景點距離。")

TAIWAN_CITIES = ["宜蘭縣", "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("1. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("2. 景點名稱關鍵字")

# 重置按鈕
if st.sidebar.button("重置回預設位置"):
    st.session_state.center_coords = (25.0478, 121.5170)
    st.rerun()

# 載入與篩選資料
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. 渲染地圖 ---
st.title(f"📍 {city_filter} 親子旅遊地圖")
st.write(f"當前中心座標：{st.session_state.center_coords[0]:.5f}, {st.session_state.center_coords[1]:.5f} (點擊地圖可更換位置)")

# 建立地圖物件
# 注意：location 使用當前的 session_state
m = folium.Map(location=st.session_state.center_coords, zoom_start=13, control_scale=True)

# 標記中心位置 (紅色星星)
folium.Marker(
    st.session_state.center_coords, 
    popup="我的中心點", 
    icon=folium.Icon(color="red", icon="star")
).add_to(m)

# 標記符合條件的景點
for _, row in filtered_df.iterrows():
    pin_color = "blue" if row["來源"] == "政府公開資料" else "green"
    popup_html = f"<b>{row['名稱']}</b><br>距離：{row['距離(km)']} km<hr>{row['介紹']}"
    
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=folium.Popup(popup_html, max_width=250),
        icon=folium.Icon(color=pin_color, icon="info-sign"),
        tooltip=row['名稱']
    ).add_to(m)

# 顯示地圖並捕捉點擊事件
# returned_objects=["last_clicked"] 是關鍵，這會回傳滑鼠點擊的座標
map_data = st_folium(
    m, 
    width="100%", 
    height=600, 
    returned_objects=["last_clicked"]
)

# --- 5. 處理點擊事件並更新座標 ---
if map_data and map_data["last_clicked"]:
    clicked_lat = map_data["last_clicked"]["lat"]
    clicked_lng = map_data["last_clicked"]["lng"]
    
    # 檢查是否與現有座標不同，避免無限循環重新渲染
    if (clicked_lat, clicked_lng) != st.session_state.center_coords:
        st.session_state.center_coords = (clicked_lat, clicked_lng)
        st.rerun() # 強制重新執行，更新距離計算與列表

# --- 6. 顯示結果列表 ---
st.subheader(f"🏠 距離最近的景點 (Top 10)")
if not filtered_df.empty:
    st.table(filtered_df[["名稱", "距離(km)", "介紹"]].head(10))
else:
    st.warning("此區域尚無符合條件的景點。")
