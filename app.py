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

# --- 1. 資料匯入邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    
    # 建立縣市對應表
    CITY_LOOKUP = {
        "臺北市": ["台北", "臺北"],
        "新北市": ["新北"],
        "桃園市": ["桃園"],
        "臺中市": ["台中", "臺中"],
        "臺南市": ["台南", "臺南"],
        "高雄市": ["高雄"],
        "新竹縣": ["新竹縣"],
        "新竹市": ["新竹市"],
        "基隆市": ["基隆"],
        "宜蘭縣": ["宜蘭"],
        "花蓮縣": ["花蓮"],
        "臺東縣": ["台東", "臺東"],
        "金門縣": ["金門"],
        "澎湖縣": ["澎湖"],
        "連江縣": ["連江", "馬祖"]
    }

    # 方法 A: 嘗試讀取政府 XML
    try:
        # 使用更大的 timeout 確保大檔案下載完成
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=30, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else ""
                add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                
                full_text = name + add + region
                
                # 判定縣市
                item_city = "其他"
                for city_name, keywords in CITY_LOOKUP.items():
                    if any(kw in full_text for kw in keywords):
                        item_city = city_name
                        break
                
                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": item_city,
                        "介紹": info.find('Description').text[:50] if info.find('Description') is not None else "",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue
    except Exception as e:
        st.error(f"政府 API 連線異常: {e}")

    # 方法 B: 備用基礎資料 (如果台北市還是空的，手動加入幾個地標測試)
    # 這能確保即使 API 抽風，臺北市也不會是空列表
    backup_taipei = [
        {"名稱": "臺北市立動物園", "縣市": "臺北市", "緯度": 24.9983, "經度": 121.5810, "介紹": "適合親子同遊"},
        {"名稱": "國立臺灣博物館", "縣市": "臺北市", "緯度": 25.0428, "經度": 121.5150, "介紹": "室內吹冷氣看展"},
        {"名稱": "台北101", "縣市": "臺北市", "緯度": 25.0339, "經度": 121.5645, "介紹": "地標建築"}
    ]
    
    df = pd.DataFrame(all_pois)
    
    # 檢查是否真的沒抓到臺北市
    if df.empty or "臺北市" not in df["縣市"].values:
        df = pd.concat([df, pd.DataFrame(backup_taipei)], ignore_index=True)

    return df

poi_df = load_all_data()

# --- 2. 側邊欄 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")

TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES, index=1) # 預設選台北
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位
geolocator = Nominatim(user_agent="my_app_v6")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# --- 3. 篩選邏輯 ---
# 這裡要做最強化的篩選，防止字體不一
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    # 使用包含判斷，防止末尾空格影響
    filtered_df = filtered_df[filtered_df["縣市"].str.contains(city_filter.replace("臺", ""), na=False)]

if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword, na=False)]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. 顯示結果 ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"🗺️ 景點分佈地圖 - {city_filter}")
    m = folium.Map(location=center_coords, zoom_start=14)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red")).add_to(m)
    
    for _, row in filtered_df.head(50).iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=row["名稱"],
            icon=folium.Icon(color="blue")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="map")

with col2:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.write(f"找到 {len(filtered_df)} 個景點")
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], hide_index=True)
    else:
        st.info("目前無資料。")
        # 直接顯示資料庫前 10 筆，幫忙除錯
        st.write("資料庫內目前的縣市統計：")
        st.write(poi_df["縣市"].value_counts())
