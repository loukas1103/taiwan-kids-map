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
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 資料匯入與強效標準化邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    
    # 標準縣市清單
    STANDARD_CITIES = [
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
        "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
        "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
        "臺東縣", "澎湖縣", "金門縣", "連江縣"
    ]

    # --- 方法 A: 政府 XML 資料 ---
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                # 新增：讀取 Region 欄位，這在政府資料中通常存放縣市名稱
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                
                # 統一將「台」轉為「臺」
                normalized_text = (region + raw_add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                # 優先判定縣市
                found_city = "其他"
                for c in STANDARD_CITIES:
                    # 同時檢查 Region 和 Address
                    if c in normalized_text:
                        found_city = c
                        break
                
                # 特殊補救：如果還是找不到，但 Region 裡有 "台北"
                if found_city == "其他" and ("台北" in region or "臺北" in region):
                    found_city = "臺北市"

                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "介紹": (info.find('Description').text[:100] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # --- 方法 B: Google 表單 CSV ---
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        sheet_df.columns = sheet_df.columns.str.strip()
        
        if '縣市' in sheet_df.columns:
            # 強化 CSV 的縣市轉換邏輯，確保「台北市」變成「臺北市」
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中").str.replace("台南", "臺南").replace("台東", "臺東")
        
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning(f"表單讀取失敗: {e}")

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        df['縣市'] = df['縣市'].astype(str).str.strip()
    
    return df

# 載入資料
poi_df = load_all_data()

# --- 2. 搜尋介面 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位邏輯
geolocator = Nominatim(user_agent="taiwan_kids_map_v4")
try:
    loc = geolocator.geocode(target_address)
    if loc:
        center_coords = (loc.latitude, loc.longitude)
    else:
        center_coords = (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 篩選邏輯
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 顯示結果 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("🗺️ 景點分佈地圖")
    m = folium.Map(location=center_coords, zoom_start=12)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    for _, row in filtered_df.head(150).iterrows():
        popup_text = f"<b>{row['名稱']}</b><br>{row['縣市']}<br>{row.get('介紹', '')}"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_text, max_width=250),
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.info("目前無資料，請嘗試調整搜尋條件。")
