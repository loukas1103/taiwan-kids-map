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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖 V8")

# --- 1. 資料匯入與強效標籤邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
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
                
                # 核心分類邏輯：先全部轉為俗體「台」進行內部判定
                check_str = (name + region + raw_add).replace("臺", "台")
                
                # 嚴格分類順序：先判斷「新北」，再判斷「台北」
                if "新北" in check_str:
                    final_city = "新北市"
                elif "台北" in check_str:
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
                    # 其他縣市通用判斷
                    city_list = ["基隆", "新竹", "苗栗", "彰化", "南投", "雲林", "嘉義", "屏東", "宜蘭", "花蓮", "台東", "金門", "澎湖", "連江"]
                    final_city = "其他"
                    for c in city_list:
                        if c in check_str:
                            # 補回正體字
                            final_city = c + ("市" if c in ["基隆", "新竹", "嘉義"] else "縣")
                            final_city = final_city.replace("台東", "臺東")
                            break
                
                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": final_city, 
                        "介紹": (info.find('Description').text[:50] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue
    except Exception as e:
        st.error(f"資料載入失敗: {e}")

    return pd.DataFrame(all_pois)

# 載入資料
poi_df = load_all_data()

# --- 2. 側邊欄搜尋 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")

TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES, index=1)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 顯示統計資料（除錯用，確認完後可刪除）
st.sidebar.markdown("---")
st.sidebar.subheader("📊 資料庫統計")
if not poi_df.empty:
    city_counts = poi_df["縣市"].value_counts()
    st.sidebar.write(f"目前臺北市景點數: {city_counts.get('臺北市', 0)}")
    if st.sidebar.checkbox("顯示所有縣市統計"):
        st.sidebar.write(city_counts)

# 定位
geolocator = Nominatim(user_agent="taiwan_kids_map_v8")
try:
    loc = geolocator.geocode(target_address.replace("台", "臺"))
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# --- 3. 篩選與地圖 ---
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword.replace("台", "臺"), na=False) | 
                              filtered_df["名稱"].str.contains(keyword.replace("臺", "台"), na=False)]

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. UI 佈局 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader(f"🗺️ 景點分佈 - {city_filter}")
    m = folium.Map(location=center_coords, zoom_start=13)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    for _, row in filtered_df.head(100).iterrows():
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=f"<b>{row['名稱']}</b><br>{row['介紹']}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.write(f"找到 {len(filtered_df)} 個景點")
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.warning("目前篩選條件下無資料。")
