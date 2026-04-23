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

# 標準縣市清單
STANDARD_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    
    # --- 方法 A: 政府 XML 資料 (觀光署) ---
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        # 加入 headers 模擬瀏覽器，避免被伺服器拒絕
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(gov_url, headers=headers, timeout=20, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                
                # 強效縣市抓取邏輯
                region = ""
                xml_region = info.find('Region')
                if xml_region is not None and xml_region.text:
                    region = xml_region.text.strip().replace("台", "臺")
                
                # 如果 Region 抓不到或不準，從地址抓
                if not any(city in region for city in STANDARD_CITIES):
                    raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                    raw_add = raw_add.replace("台", "臺")
                    for city in STANDARD_CITIES:
                        if city in raw_add:
                            region = city
                            break
                
                # 確保格式為 "臺北市" 而非 "臺北"
                if region == "臺北": region = "臺北市"
                
                # 座標讀取與清洗
                px = info.find('Px').text.strip() if info.find('Px') is not None else None
                py = info.find('Py').text.strip() if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": region if region else "其他", 
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
        # 強制指定編碼，處理中文亂碼
        sheet_df = pd.read_csv(SHEET_CSV_URL, encoding='utf-8')
        # 清除欄位名稱的空白與特殊符號 (解決 rename 失敗的主因)
        sheet_df.columns = [re.sub(r'[^\w]', '', col) for col in sheet_df.columns]
        
        # 建立欄位映射 (請確認您表單內的實際標題)
        # 如果您的表單標題是 "景點名稱" 或 "景點", 都會轉為 "名稱"
        mapping = {
            '景點名稱': '名稱', '名稱': '名稱', '景點': '名稱',
            '縣市': '縣市', '地址': '縣市',
            '緯度': '緯度', 'Lat': '緯度', 'latitude': '緯度',
            '經度': '經度', 'Lng': '經度', 'longitude': '經度',
            '介紹': '介紹', '備註': '介紹'
        }
        sheet_df = sheet_df.rename(columns=mapping)
        
        # 再次檢查必要欄位是否存在
        if '名稱' in sheet_df.columns and '緯度' in sheet_df.columns:
            # 縣市標準化
            if '縣市' in sheet_df.columns:
                def clean_sheet_city(x):
                    x = str(x).replace("台", "臺")
                    for city in STANDARD_CITIES:
                        if city in x: return city
                    return x
                sheet_df['縣市'] = sheet_df['縣市'].apply(clean_sheet_city)
            
            # 只挑選主程式需要的欄位，避免髒資料
            needed = ["名稱", "縣市", "介紹", "緯度", "經度"]
            final_sheet_df = sheet_df[[c for c in needed if c in sheet_df.columns]].copy()
            all_pois.extend(final_sheet_df.to_dict('records'))
            
    except Exception as e:
        st.warning(f"表單讀取失敗: {e}")

    # --- 最後資料清洗 ---
    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        df['縣市'] = df['縣市'].astype(str).str.strip()
    
    return df

# 載入資料
poi_df = load_all_data()

# --- UI 介面 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + STANDARD_CITIES, index=1) # 預設選臺北市
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位邏輯
geolocator = Nominatim(user_agent="taiwan_kids_map_v6")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 篩選
filtered_df = poi_df.copy()
if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 距離計算
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 輸出顯示 ---
st.title("🎡 全台親子旅遊自動化查詢站")
col_map, col_info = st.columns([2, 1])

with col_map:
    m = folium.Map(location=center_coords, zoom_start=13)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    for _, row in filtered_df.head(150).iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=f"<b>{row['名稱']}</b><br>{row['縣市']}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader(f"📋 {city_filter} 景點列表")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.info("無相符資料，請調整搜尋條件。")
