import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 設定頁面配置為寬螢幕
st.set_page_config(layout="wide", page_title="台灣親子旅遊搜尋器")

# --- 模擬景點數據 (實際應用可讀取 CSV 或資料庫) ---
@st.cache_data
def get_poi_data():
    data = {
        "名稱": ["台北市立動物園", "新竹綠世界", "台中科博館", "高雄駁二", "桃園Xpark"],
        "縣市": ["台北市", "新竹縣", "台中市", "高雄市", "桃園市"],
        "緯度": [24.9983, 24.6974, 24.1533, 22.6199, 25.0125],
        "經度": [121.5810, 121.0694, 120.6660, 120.2815, 121.2165]
    }
    return pd.DataFrame(data)

poi_df = get_poi_data()

# --- 側邊欄：搜尋條件 (需求 1 & 2) ---
st.sidebar.header("🔍 搜尋設定")
target_address = st.sidebar.text_input("1. 輸入您的位置 (地址或地標)", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部"] + list(poi_df["縣市"].unique()))
keyword = st.sidebar.text_input("3. 景點關鍵字搜尋")

# 定位目標座標
geolocator = Nominatim(user_agent="taiwan_kids_travel_app")
try:
    location = geolocator.geocode(target_address)
    if location:
        center_coords = (location.latitude, location.longitude)
    else:
        center_coords = (25.0478, 121.5170) # 預設台北車站
except:
    center_coords = (25.0478, 121.5170)

# --- 資料篩選邏輯 ---
filtered_df = poi_df.copy()
if city_filter != "全部":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]
if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword)]

# 計算距離 (需求 4)
def calc_dist(row):
    return round(geodesic(center_coords, (row["緯度"], row["經度"])).km, 2)

filtered_df["距離(km)"] = filtered_df.apply(calc_dist, axis=1)
filtered_df = filtered_df.sort_values("距離(km)")

# --- 網頁佈局 ---
col_map, col_info = st.columns([2, 1]) # 中間地圖佔2份，右側資訊佔1份

with col_map:
    st.subheader("🗺️ 景點地圖")
    # 建立地圖 (需求 3)
    m = folium.Map(location=center_coords, zoom_start=12)
    
    # 紅色圖釘：中心點
    folium.Marker(
        center_coords, 
        popup=f"您的位置: {target_address}", 
        icon=folium.Icon(color="red", icon="info-sign")
    ).add_to(m)
    
    # 藍色圖釘：周邊景點
    for _, row in filtered_df.iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=f"{row['名稱']} ({row['距離(km)']} km)",
            icon=folium.Icon(color="blue", icon="cloud")
        ).add_to(m)
    
    st_folium(m, width=800, height=600)

with col_info:
    st.subheader("📋 景點列表")
    st.write(f"中心點：{target_address}")
    # 顯示搜尋結果 (需求 4)
    st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True)
