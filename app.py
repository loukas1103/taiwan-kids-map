import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import time

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖", page_icon="📍")

# --- 初始化 Session State ---
if 'center_coords' not in st.session_state:
    st.session_state.center_coords = (25.0478, 121.5170)  # 預設台北車站
if 'last_address' not in st.session_state:
    st.session_state.last_address = "台北車站"

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

# --- 2. 地理位置搜尋邏輯 ---
def update_location(address):
    """處理地址轉換座標並存入 Session"""
    if not address:
        return
    
    # 增加 "台灣" 關鍵字以提高精準度
    search_query = f"{address}, Taiwan"
    geolocator = Nominatim(user_agent="taiwan_kids_map_v2_fix")
    
    try:
        with st.spinner('正在定位中...'):
            # 增加延遲避免被 Nominatim 封鎖
            time.sleep(1) 
            loc = geolocator.geocode(search_query)
            if loc:
                st.session_state.center_coords = (loc.latitude, loc.longitude)
                st.session_state.last_address = address
                st.success(f"成功定位至：{address}")
            else:
                st.warning("找不到該位置，請嘗試更精確的地址（例如：台北市信義區...）")
    except Exception as e:
        st.error("定位服務繁忙，請稍後再試或檢查網路。")

# --- 3. 側邊欄介面 ---
st.sidebar.header("🔍 景點搜尋")

# 地址輸入與按鈕
target_address = st.sidebar.text_input("1. 輸入您的中心位置", st.session_state.last_address)
if st.sidebar.button("確認定位"):
    update_location(target_address)

TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點名稱關鍵字")

# 載入資料
poi_df = load_base_data()

# 篩選邏輯
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()
if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算距離 (使用 Session 中的中心點)
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. 渲染地圖 ---
st.title(f"📍 {city_filter} 親子旅遊圖釘地圖")
st.markdown(f"🏠 當前中心：**{st.session_state.last_address}**")

# 建立地圖
m = folium.Map(location=st.session_state.center_coords, zoom_start=14, control_scale=True)

# 標記中心位置
folium.Marker(
    st.session_state.center_coords, 
    popup="我的位置", 
    icon=folium.Icon(color="red", icon="home")
).add_to(m)

# 標記景點
for _, row in filtered_df.head(100).iterrows(): # 限制數量提升流暢度
    pin_color = "blue" if row["來源"] == "政府公開資料" else "green"
    
    popup_html = f"""
    <div style="width: 200px; font-family: sans-serif;">
        <h4 style="margin-bottom: 5px; color: #1f77b4;">{row['名稱']}</h4>
        <p style="margin: 0; font-size: 0.9em;"><b>距離：</b>{row['距離(km)']} km</p>
        <hr style="margin: 8px 0;">
        <div style="max-height: 100px; overflow-y: auto; font-size: 0.85em;">
            {row['介紹']}
        </div>
    </div>
    """
    
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=folium.Popup(popup_html, max_width=250),
        icon=folium.Icon(color=pin_color, icon="info-sign"),
        tooltip=row['名稱']
    ).add_to(m)

# 顯示地圖
st_folium(m, width="100%", height=600, key="main_map", returned_objects=[])

st.caption(f"顯示 {len(filtered_df)} 個景點。中心點座標: {st.session_state.center_coords}")
