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

# 設定頁面
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 資料匯入整合邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []

    # --- 方法 A: 政府資料開放平台 (XML) ---
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        # 加入 verify=False 解決之前的 SSL 錯誤
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                px = info.find('Px').text # 經度
                py = info.find('Py').text # 緯度
                if px and py:
                    all_pois.append({
                        "名稱": info.find('Name').text if info.find('Name') is not None else "未知景點",
                        "縣市": (info.find('Add').text[0:3]) if info.find('Add') is not None else "其他",
                        "介紹": (info.find('Description').text[:100] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue
    except Exception as e:
        st.error(f"政府 XML 資料匯入失敗: {e}")

    # --- 方法 B: Google 表單試算表 (CSV) ---
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        # 清除 CSV 欄位空格
        sheet_df.columns = sheet_df.columns.str.strip()
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning(f"Google 表單資料讀取失敗: {e}")

    # 轉成 DataFrame 並進行資料清洗
    df = pd.DataFrame(all_pois)
    if not df.empty:
        df.columns = df.columns.str.strip()
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    
    return df

# 執行匯入
with st.spinner('正在同步最新景點資訊...'):
    poi_df = load_all_data()

# --- 2. 搜尋邏輯 ---
TAIWAN_CITIES = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]

st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 地理定位中心點
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
        return 999.0

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(calc_dist, axis=1)
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 畫面顯示 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("🗺️ 景點分佈地圖")
    # 先建立地圖物件
    m = folium.Map(location=center_coords, zoom_start=12)
    
    # 畫出中心位置 (紅色)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    # 畫出景點 (藍色)
    if not filtered_df.empty:
        # 只顯示前 100 個最近的景點，避免地圖太卡
        for _, row in filtered_df.head(100).iterrows():
            popup_text = f"<b>{row['名稱']}</b><br>{row.get('介紹', '暫無介紹')}"
            folium.Marker(
                [row["緯度"], row["經度"]],
                popup=folium.Popup(popup_text, max_width=250),
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
    
    # 顯示地圖
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        # 顯示欄位整理
        display_cols = ["名稱", "縣市", "距離(km)"]
        st.dataframe(filtered_df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.write("目前無資料，請嘗試調整搜尋條件。")
