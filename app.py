import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊景點查詢")

# --- 1. 定義全台灣縣市清單 ---
TAIWAN_CITIES = [
    "基隆市", "台北市", "新北市", "桃園市", "新竹市", "新竹縣", "苗栗縣", 
    "台中市", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "台南市", 
    "高雄市", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"
]

# --- 2. 模擬景點數據 (含介紹內容) ---
# 實際開發時，您可以將此部分替換為讀取 CSV 檔案
@st.cache_data
def get_poi_data():
    data = {
        "名稱": ["台北市立動物園", "野柳地質公園", "桃園 Xpark", "台中科博館", "清境農場", "台南奇美博物館", "高雄駁二特區", "屏東海生館"],
        "縣市": ["台北市", "新北市", "桃園市", "台中市", "南投縣", "台南市", "高雄市", "屏東縣"],
        "介紹": [
            "全台規模最大的動物園，適合全家大小親近自然與動物。",
            "著名的女王頭地景，是地理教育與美拍的絕佳地點。",
            "都會型水生公園，結合聲光效果的沉浸式水族體驗。",
            "豐富的自然科學展示，恐龍廳是小學生的最愛。",
            "高山草原風光，可以近距離與綿羊互動及觀賞剪羊毛秀。",
            "歐式建築風格，收藏大量西方藝術品、兵器與動物標本。",
            "藝術與港灣風情的結合，有許多手作店鋪與大草皮供跑跳。",
            "台灣最大的海洋生物館，設有海底隧道與企鵝餵食秀。"
        ],
        "緯度": [24.9983, 25.2064, 25.0125, 24.1533, 24.0586, 22.9348, 22.6199, 22.0465],
        "經度": [121.5810, 121.6914, 121.2165, 120.6660, 121.1631, 120.2260, 120.2815, 120.6975]
    }
    return pd.DataFrame(data)

poi_df = get_poi_data()

# --- 3. 側邊欄：搜尋條件 (左側) ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的地址或地標", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字 (例如: 動物、博物館)")

# 定位座標邏輯
geolocator = Nominatim(user_agent="taiwan_kids_travel_search")
try:
    location = geolocator.geocode(target_address)
    if location:
        center_coords = (location.latitude, location.longitude)
    else:
        center_coords = (25.0478, 121.5170) # 查無結果預設台北車站
except:
    center_coords = (25.0478, 121.5170)

# --- 4. 資料篩選與距離計算 ---
filtered_df = poi_df.copy()
if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]
if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword) | filtered_df["介紹"].str.contains(keyword)]

# 計算與紅色圖釘的距離
def calc_dist(row):
    return round(geodesic(center_coords, (row["緯度"], row["經度"])).km, 2)

filtered_df["距離(km)"] = filtered_df.apply(calc_dist, axis=1)
filtered_df = filtered_df.sort_values("距離(km)")

# --- 5. 網頁佈局 ---
col_map, col_info = st.columns([2, 1])

# 中間區域：地圖顯示
with col_map:
    st.subheader("🗺️ 景點分佈地圖")
    m = folium.Map(location=center_coords, zoom_start=12, control_scale=True)
    
    # 紅色圖釘 (中心點)
    folium.Marker(
        center_coords, 
        popup=f"<b>當前位置</b><br>{target_address}", 
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)
    
    # 藍色圖釘 (景點)
    for _, row in filtered_df.iterrows():
        # 設定彈出視窗的 HTML 內容
        popup_html = f"""
        <div style='width:200px'>
            <h4>{row['名稱']}</h4>
            <p><b>距離:</b> {row['距離(km)']} km</p>
            <p><b>介紹:</b> {row['介紹']}</p>
        </div>
        """
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=row["名稱"], # 滑鼠指上去顯示名稱
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    
    st_folium(m, width="100%", height=650)

# 右側區域：景點列表
with col_info:
    st.subheader("📋 搜尋結果列表")
    if filtered_df.empty:
        st.warning("查無符合條件的景點。")
    else:
        # 顯示景點卡片或表格
        for idx, row in filtered_df.iterrows():
            with st.container():
                st.markdown(f"### {row['名稱']}")
                st.caption(f"📍 {row['縣市']} | 📏 距離 {row['距離(km)']} km")
                st.write(row['介紹'])
                st.divider()
