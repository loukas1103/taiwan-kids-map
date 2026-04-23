import streamlit as st
import pandas as pd
import folium
import requests
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import io

# 設定頁面
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 資料匯入整合邏輯 ---
@st.cache_data(ttl=3600)  # 每小時自動重新抓取一次 (需求 3)
def load_all_data():
    all_pois = []

    # --- 方法 A: 政府資料開放平台 (需求 1) ---
    # 使用觀光署觀光資訊 API (範例使用 JSON 格式)
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.json" # 這裡以景點 API 為例
        # 註：實際 API URL 請根據政府平台最新路徑替換
        response = requests.get(gov_url, timeout=10)
        gov_data = response.json()
        for item in gov_data['XML_Head']['Infos']['Info']:
            all_pois.append({
                "名稱": item.get('Name'),
                "縣市": item.get('Add')[0:3], # 擷取前三字
                "介紹": item.get('Description')[:100] + "...", # 限制字數
                "緯度": float(item.get('Py')),
                "經度": float(item.get('Px'))
            })
    except Exception as e:
        st.error(f"政府資料匯入失敗: {e}")

    # --- 方法 B: Google 表單試算表 (需求 2) ---
    # 請將下方網址替換為你「發佈到網路」的 CSV 網址
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/您的ID/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        # 確保試算表欄位名稱與程式一致
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning("Google 表單資料暫無數據或連結錯誤。")

    return pd.DataFrame(all_pois)

# 啟動時自動執行匯入
with st.spinner('正在同步最新景點資訊...'):
    poi_df = load_all_data()

# --- 2. 介面設計與搜尋邏輯 (與先前一致) ---
TAIWAN_CITIES = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]

st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 地理定位
geolocator = Nominatim(user_agent="taiwan_kids_travel_v2")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 篩選資料
filtered_df = poi_df.copy()
if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]
if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword, na=False)]

# 計算距離
def calc_dist(row):
    try:
        return round(geodesic(center_coords, (row["緯度"], row["經度"])).km, 2)
    except:
        return 9999

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(calc_dist, axis=1)
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 畫面顯示 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("🗺️ 景點地圖")
    m = folium.Map(location=center_coords, zoom_start=12)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red")).add_to(m)
    
    for _, row in filtered_df.iterrows():
        popup_text = f"<b>{row['名稱']}</b><br>{row['介紹']}"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_text, max_width=250),
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600)

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.write("目前無資料。")
