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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖 V9")

# --- 1. 資料匯入與【郵遞區號】精準標籤邏輯 ---
# 增加一個 v9 參數來強制重新整理快取，避免讀到舊資料
@st.cache_data(ttl=3600)
def load_all_data(version="v9"):
    all_pois = []
    
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=30, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else ""
                raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                zip_code = info.find('Zipcode').text.strip() if info.find('Zipcode') is not None else ""
                
                # --- 強力分類邏輯 ---
                final_city = "其他"
                
                # 1. 優先使用【郵遞區號】判定 (臺北市全區皆為 1 開頭)
                if zip_code.startswith("1"):
                    final_city = "臺北市"
                # 2. 次要使用關鍵字判定
                else:
                    check_str = (region + raw_add + name).replace("臺", "台")
                    
                    # 排除新北
                    if "新北" in check_str:
                        final_city = "新北市"
                    elif "台北" in check_str or "台北" in check_str:
                        final_city = "臺北市"
                    elif "桃園" in check_str:
                        final_city = "桃園市"
                    elif "台中" in check_str:
                        final_city = "臺中市"
                    elif "台南" in check_str:
                        final_city = "臺南市"
                    elif "高雄" in check_str:
                        final_city = "高雄市"
                    else:
                        city_keywords = {
                            "基隆": "基隆市", "新竹": "新竹市", "苗栗": "苗栗縣", 
                            "彰化": "彰化縣", "南投": "南投縣", "雲林": "雲林縣", 
                            "嘉義": "嘉義市", "屏東": "屏東縣", "宜蘭": "宜蘭縣", 
                            "花蓮": "花蓮縣", "台東": "臺東縣", "金門": "金門縣", 
                            "澎湖": "澎湖縣", "連江": "連江縣"
                        }
                        for kw, full_name in city_keywords.items():
                            if kw in check_str:
                                final_city = full_name
                                break
                
                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": final_city, 
                        "介紹": (info.find('Description').text[:50] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px),
                        "郵遞區號": zip_code
                    })
            except:
                continue
    except Exception as e:
        st.error(f"資料載入失敗: {e}")

    return pd.DataFrame(all_pois)

# 載入資料
poi_df = load_all_data(version="v9")

# --- 2. 側邊欄與搜尋 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")

TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES, index=1)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# --- 除錯資訊 ---
st.sidebar.markdown("---")
st.sidebar.subheader("📊 資料庫統計")
if not poi_df.empty:
    counts = poi_df["縣市"].value_counts()
    st.sidebar.write(f"臺北市總數: {counts.get('臺北市', 0)}")
    st.sidebar.write(f"新北市總數: {counts.get('新北市', 0)}")
    if st.sidebar.button("🗑️ 清除快取並重整"):
        st.cache_data.clear()
        st.rerun()

# 定位
geolocator = Nominatim(user_agent="taiwan_kids_map_v9")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# --- 3. 篩選與地圖 ---
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword, na=False)]

# --- 4. 顯示 ---
col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"🗺️ 景點分佈 - {city_filter}")
    m = folium.Map(location=center_coords, zoom_start=13)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red")).add_to(m)
    
    for _, row in filtered_df.head(100).iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=row["名稱"],
            icon=folium.Icon(color="blue")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col2:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.write(f"找到 {len(filtered_df)} 個景點")
        st.dataframe(filtered_df[["名稱", "縣市", "郵遞區號"]], use_container_width=True, hide_index=True)
    else:
        st.warning("查無資料")
        if city_filter == "臺北市":
            st.write("目前資料庫中前 10 筆原始資料參考：")
            st.write(poi_df.head(10))
