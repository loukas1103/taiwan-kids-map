import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

st.set_page_config(page_title="台灣親子旅遊地圖", layout="wide")
st.title("👨‍👩‍👧‍👦 台灣親子旅遊景點查詢")

# 讀取資料
@st.cache_data
def load_data():
    try:
        # 請確保你的 locations.csv 檔案與此程式在同一資料夾
        return pd.read_csv('locations.csv')
    except:
        return pd.DataFrame(columns=['名稱', '城市', '類型', '分齡', 'lat', 'lon', '介紹'])

df = load_data()

# --- 側邊欄設計 ---
st.sidebar.header("📍 位置與篩選")

# 1. 起點改為輸入地址
search_address = st.sidebar.text_input("🏠 輸入你的地標或地址", placeholder="例如：新北市新店區北新路一段...")
user_coords = None
    
if search_address:
    try:
        # 使用 Nominatim 進行地理編碼
        geolocator = Nominatim(user_agent="taiwan_kids_app_v2")
        location = geolocator.geocode(search_address)
        if location:
            user_coords = (location.latitude, location.longitude)
            st.sidebar.success(f"已定位：{search_address}")
        else:
            st.sidebar.error("找不到該地址，請輸入更詳細的地址資訊。")
    except:
        st.sidebar.warning("地址服務忙碌中，請稍後再試。")

# 2. 縣市選擇：預設只顯示台北市與新北市
all_cities = sorted(df['城市'].unique())
# 找出存在於資料中且屬於雙北的選項
default_cities = [c for c in all_cities if c in ['台北市', '新北市']]

city_choice = st.sidebar.multiselect(
    "選擇縣市", 
    options=all_cities, 
    default=default_cities
)

# 3. 關鍵字搜尋
search_query = st.sidebar.text_input("🔎 搜尋景點關鍵字")

if st.sidebar.button("🔄 同步最新雲端資料"):
    with st.spinner("同步中..."):
        from sync_data import sync_from_google_sheets
        sync_from_google_sheets()
        st.success("同步完成！請重新整理網頁。")
        
# --- 資料處理邏輯 ---

# 過濾條件
filtered_df = df[
    (df['城市'].isin(city_choice)) & 
    (df['名稱'].str.contains(search_query, na=False))
].copy()

# 計算距離並排序
if user_coords:
    distances = []
    for idx, row in filtered_df.iterrows():
        dest = (row['lat'], row['lon'])
        dist = geodesic(user_coords, dest).km
        distances.append(round(dist, 1))
    filtered_df['距離(km)'] = distances
    filtered_df = filtered_df.sort_values(by='距離(km)')

# --- 畫面配置 ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("🗺️ 互動地圖 (點擊標記查看介紹)")
    
    # 地圖中心邏輯
    map_center = user_coords if user_coords else [25.03, 121.5] # 預設中心在台北
    zoom_val = 13 if user_coords else 11
    m = folium.Map(location=map_center, zoom_start=zoom_val)
    
    # 標記起點地址 (紅色)
    if user_coords:
        folium.Marker(
            user_coords, 
            popup="我的位置", 
            icon=folium.Icon(color='red', icon='home')
        ).add_to(m)
    
    # 標記景點 (藍色)
    for idx, row in filtered_df.iterrows():
        # 製作彈出視窗的內容 (支援 HTML)
        popup_html = f"""
            <div style='width: 200px;'>
                <h4>{row['名稱']}</h4>
                <p><b>介紹：</b>{row['介紹']}</p>
                <p><b>分齡：</b>{row['分齡']}</p>
            </div>
        """
        folium.Marker(
            [row['lat'], row['lon']], 
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=row['名稱'],
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)
        
    st_folium(m, width=700, height=600, key="main_map")

with col2:
    st.subheader("📋 景點清單")
    if not user_coords:
        st.info("💡 輸入地址後可依距離排序")

    for idx, row in filtered_df.iterrows():
        display_title = f"📍 {row['名稱']}"
        if user_coords:
            display_title += f" ({row['距離(km)']} km)"
            
        with st.expander(display_title):
            st.write(f"**分類：** {row['類型']}")
            st.write(f"**適合年齡：** {row['分齡']}")
            st.write(row['介紹'])
            nav_url = f"https://www.google.com/maps/dir/?api=1&destination={row['lat']},{row['lon']}"
            st.markdown(f"[🚗 開啟 Google 地圖導航]({nav_url})")
