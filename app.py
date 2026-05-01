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

st.set_page_config(layout="wide", page_title="全台親子旅遊地圖")

# --- 1. 資料載入 (維持快取) ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip()
                px = info.find('Px').text
                py = info.find('Py').text
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else ""
                if px and py:
                    all_pois.append({"名稱": name, "緯度": float(py), "經度": float(px), "介紹": desc})
            except: continue
    except: st.error("資料庫連線失敗")
    return pd.DataFrame(all_pois)

# --- 2. 初始化 Session State (紀錄座標) ---
if 'center_lat' not in st.session_state:
    st.session_state.center_lat = 25.0478  # 預設台北車站
if 'center_lon' not in st.session_state:
    st.session_state.center_lon = 121.5170

# --- 3. 側邊欄控制面版 ---
st.sidebar.header("📍 定位設定")

# 方案 A: 手動微調座標 (不求人，最穩定)
with st.sidebar.expander("手動調整座標", expanded=False):
    st.session_state.center_lat = st.number_input("中心緯度", value=st.session_state.center_lat, format="%.4f")
    st.session_state.center_lon = st.number_input("中心經度", value=st.session_state.center_lon, format="%.4f")

# 搜尋設定
search_radius = st.sidebar.slider("搜尋半徑 (km)", 1, 20, 5)
keyword = st.sidebar.text_input("關鍵字搜尋")

# --- 4. 邏輯運算 ---
poi_df = load_base_data()
center_coords = (st.session_state.center_lat, st.session_state.center_lon)

# 計算距離並篩選
if not poi_df.empty:
    poi_df["距離(km)"] = poi_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = poi_df[poi_df["距離(km)"] <= search_radius].copy()
    if keyword:
        filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword, na=False)]
    filtered_df = filtered_df.sort_values("距離(km)")
else:
    filtered_df = pd.DataFrame()

# --- 5. 地圖渲染 ---
st.title("🎡 親子旅遊地圖")
st.markdown(f"💡 **定位新招**：在地圖上**任意處點擊**，即可重新設定中心點！目前搜尋範圍：{search_radius}km")

# 建立地圖
m = folium.Map(location=center_coords, zoom_start=14, control_scale=True)

# 紅色圖釘 - 中心點
folium.Marker(
    center_coords, 
    popup="目前搜尋中心", 
    icon=folium.Icon(color="red", icon="screenshot", prefix='fa'),
    tooltip="中心定位點"
).add_to(m)

# 搜尋範圍圈
folium.Circle(
    radius=search_radius * 1000,
    location=center_coords,
    color="red",
    fill=True,
    fill_opacity=0.05
).add_to(m)

# 標記景點
for _, row in filtered_df.iterrows():
    popup_html = f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']}km<br><br>{row['介紹'][:100]}..."
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=folium.Popup(popup_html, max_width=250),
        icon=folium.Icon(color="blue", icon="child", prefix='fa')
    ).add_to(m)

# --- 6. 捕捉地圖點擊事件 ---
# 關鍵：使用 st_folium 並捕捉 returned_objects
map_data = st_folium(m, width="100%", height=600, key="main_map")

# 當使用者點擊地圖時，更新 Session State 並觸發重新整理
if map_data and map_data.get("last_clicked"):
    clicked = map_data["last_clicked"]
    if (clicked["lat"] != st.session_state.center_lat) or (clicked["lng"] != st.session_state.center_lon):
        st.session_state.center_lat = clicked["lat"]
        st.session_state.center_lon = clicked["lng"]
        st.rerun()  # 立即重新執行，地圖會重新對準點擊位置

# 顯示下方列表
if not filtered_df.empty:
    st.dataframe(filtered_df[["名稱", "距離(km)"]], use_container_width=True)
