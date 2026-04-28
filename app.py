import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊查詢站")

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
        # 政府公開資料
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

    # 社群回報資料 (Google Sheet)
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

# --- 2. 地理位置快取 (加速關鍵) ---
@st.cache_data(ttl=86400)
def get_coordinates(address):
    geolocator = Nominatim(user_agent="taiwan_kids_map_v10")
    try:
        loc = geolocator.geocode(address)
        if loc:
            return (loc.latitude, loc.longitude)
    except:
        pass
    return (25.0478, 121.5170) # 預設台北車站

# --- 3. 介面設計 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 獲取中心座標
center_coords = get_coordinates(target_address)

# 載入資料
poi_df = load_base_data()

# 篩選邏輯
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算距離與排序
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)").reset_index(drop=True)

# --- 4. 渲染頁面 ---
st.title(f"📍 {city_filter} 親子旅遊查詢系統")

col1, col2 = st.columns([2, 1])

with col1:
    # 建立地圖
    m = folium.Map(location=center_coords, zoom_start=14)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    # 繪製 2KM 參考圓圈
    folium.Circle(
        radius=2000,
        location=center_coords,
        color="crimson",
        fill=True,
        fill_color="crimson",
        fill_opacity=0.05
    ).add_to(m)
    
    # 標記景點
    for _, row in filtered_df.iterrows():
        pin_color = "blue" if row["來源"] == "政府公開資料" else "green"
        popup_content = f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']} km"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_content, max_width=200),
            icon=folium.Icon(color=pin_color, icon="info-sign")
        ).add_to(m)
        
    st_folium(m, width="100%", height=600, key="main_map")

with col2:
    st.subheader("📋 景點清單")
    if not filtered_df.empty:
        # 顯示清單，並允許選取
        st.write("點擊下方表格選取景點查看介紹：")
        selected_indices = st.dataframe(
            filtered_df[["名稱", "距離(km)"]], 
            use_container_width=True, 
            hide_index=False,
            on_select="rerun",
            selection_mode="single-row"
        )
        
        # 景點介紹顯示區
        st.divider()
        if len(selected_indices.selection.rows) > 0:
            idx = selected_indices.selection.rows[0]
            selected_spot = filtered_df.iloc[idx]
            st.markdown(f"### ℹ️ {selected_spot['名稱']}")
            st.info(selected_spot['介紹'])
        else:
            st.caption("請從表格中選取一個景點以查看詳細介紹。")
    else:
        st.info("目前的條件下無相符景點。")

# 頁尾說明
st.caption("資料來源：交通部觀光署公開資料庫、社群協作表格。")
