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

st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 資料匯入與強效標準化 ---
@st.cache_data(ttl=600) # 暫時縮短快取時間以便除錯
def load_all_data():
    all_pois = []
    
    # 標準縣市清單 (統一使用「臺」)
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

    # --- 方法 A: 政府 XML ---
    try:
        # 使用另一個備用 API 網址提升穩定性
        gov_url = "https://gis.taiwan.net.tw/XMLReleaseALL_ASPX/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=20, verify=False)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall(".//Info")
            for info in items:
                try:
                    name = info.find('Name').text.strip() if info.find('Name') is not None else "未知"
                    add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                    
                    # 強制標準化地址中的台/臺
                    norm_add = add.replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                    
                    # 辨識縣市
                    found_city = "其他"
                    for c in STANDARD_CITIES:
                        if c in norm_add:
                            found_city = c
                            break
                    
                    px = info.find('Px').text
                    py = info.find('Py').text
                    
                    if px and py:
                        all_pois.append({
                            "名稱": name,
                            "縣市": found_city, 
                            "介紹": (info.find('Description').text[:50] + "...") if info.find('Description') is not None else "無",
                            "緯度": float(py),
                            "經度": float(px)
                        })
                except:
                    continue
    except Exception as e:
        st.error(f"XML 抓取失敗: {e}")

    # --- 方法 B: Google Sheet CSV ---
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        sheet_df.columns = sheet_df.columns.str.strip()
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北")
        all_pois.extend(sheet_df.to_dict('records'))
    except:
        pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        df['縣市'] = df['縣市'].astype(str).str.strip()
    return df

# 載入資料
poi_df = load_all_data()

# --- 2. 介面與篩選 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"])
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位中心
geolocator = Nominatim(user_agent="taiwan_kids_final")
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
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword.replace("台", "臺"), na=False)]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1)
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 顯示 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader(f"🗺️ {city_filter} 景點地圖 (找到 {len(filtered_df)} 筆)")
    m = folium.Map(location=center_coords, zoom_start=13)
    folium.Marker(center_coords, popup="目前中心", icon=folium.Icon(color="red")).add_to(m)
    
    # 只畫前 80 筆最近的，確保地圖跑得動
    for _, row in filtered_df.head(80).iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=f"{row['名稱']}",
            icon=folium.Icon(color="blue")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key=f"map_{city_filter}_{keyword}")

with col_info:
    st.subheader("📋 景點清單")
    st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]].head(50), use_container_width=True, hide_index=True)

# --- 除錯看板 (若臺北市還是 0 筆，請看這裡) ---
st.divider()
st.write("### 🛠️ 系統除錯資訊")
st.write(f"資料庫總筆數: {len(poi_df)}")
if not poi_df.empty:
    st.write("各縣市資料統計:", poi_df['縣市'].value_counts())
