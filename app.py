import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
import re
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
    
    # 定義標準縣市與對應的關鍵字
    # 這裡將「台北/臺北」統一指向「臺北市」
    CITY_LOOKUP = {
        "臺北市": ["臺北", "台北"],
        "新北市": ["新北"],
        "桃園市": ["桃園"],
        "臺中市": ["臺中", "台中"],
        "臺南市": ["臺南", "台南"],
        "高雄市": ["高雄"],
        "基隆市": ["基隆"],
        "新竹縣": ["新竹縣"],
        "新竹市": ["新竹市"],
        "苗栗縣": ["苗栗"],
        "彰化縣": ["彰化"],
        "南投縣": ["南投"],
        "雲林縣": ["雲林"],
        "嘉義縣": ["嘉義縣"],
        "嘉義市": ["嘉義市"],
        "屏東縣": ["屏東"],
        "宜蘭縣": ["宜蘭"],
        "花蓮縣": ["花蓮"],
        "臺東縣": ["臺東", "台東"],
        "澎湖縣": ["澎湖"],
        "金門縣": ["金門"],
        "連江縣": ["連江", "馬祖"]
    }

    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                
                # 合併地址與區域資訊進行比對
                full_info = (region + raw_add)
                
                found_city = "其他"
                # 掃描地址，只要中其中一個關鍵字就歸類
                for city_name, keywords in CITY_LOOKUP.items():
                    if any(kw in full_info for kw in keywords):
                        found_city = city_name
                        break
                
                px = info.find('Px').text if info.find('Px') is not None else None
                py = info.find('Py').text if info.find('Py') is not None else None
                
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
        # 統一處理 CSV 的縣市欄位
        if '縣市' in sheet_df.columns:
            def normalize_city(val):
                val = str(val)
                for city_name, keywords in CITY_LOOKUP.items():
                    if any(kw in val for kw in keywords):
                        return city_name
                return "其他"
            sheet_df['縣市'] = sheet_df['縣市'].apply(normalize_city)
        
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning(f"表單讀取失敗: {e}")

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    
    return df

# 載入資料
poi_df = load_all_data()

# --- 2. 搜尋介面 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")

# 選單統一使用「臺北市」
TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位邏輯
geolocator = Nominatim(user_agent="taiwan_kids_map_v5")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# --- 篩選邏輯 ---
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    # 支援台/臺模糊搜尋
    k_alt = keyword.replace("臺", "台") if "臺" in keyword else keyword.replace("台", "臺")
    filtered_df = filtered_df[
        filtered_df["名稱"].str.contains(keyword, na=False) | 
        filtered_df["名稱"].str.contains(k_alt, na=False)
    ]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 顯示結果 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader(f"🗺️ 景點分佈地圖 - {city_filter}")
    m = folium.Map(location=center_coords, zoom_start=12)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    for _, row in filtered_df.head(100).iterrows():
        popup_text = f"<b>{row['名稱']}</b><br>{row['縣市']}"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_text, max_width=250),
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.write(f"找到 {len(filtered_df)} 個景點")
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.warning("目前無資料。")
        # 除錯區：列出資料庫前 5 筆，確認縣市欄位內容
        st.write("資料庫範例（檢查縣市名稱）：")
        st.write(poi_df[["名稱", "縣市"]].head(5))
