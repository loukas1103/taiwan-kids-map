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

st.set_page_config(layout="wide", page_title="全台親子旅遊地圖 V11")

# --- 1. 資料解析核心 (修正座標欄位) ---
@st.cache_data(ttl=3600)
def load_all_data(version="v11"):
    all_pois = []
    stats = {"total_read": 0, "skipped_no_coords": 0, "taipei_count": 0}
    
    try:
        # 政府觀光開放平台 XML
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=30, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            stats["total_read"] += 1
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else ""
                raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                zip_code = info.find('Zipcode').text.strip() if info.find('Zipcode') is not None else ""
                
                # --- 核心修正：嘗試讀取多種可能的座標欄位 ---
                # 優先嘗試您提供的 Parkinginfo_Px/Py，若無則嘗試標準 Px/Py
                px_node = info.find('Parkinginfo_Px') if info.find('Parkinginfo_Px') is not None else info.find('Px')
                py_node = info.find('Parkinginfo_Py') if info.find('Parkinginfo_Py') is not None else info.find('Py')
                
                px = px_node.text if px_node is not None else None
                py = py_node.text if py_node is not None else None
                
                if not px or not py:
                    stats["skipped_no_coords"] += 1
                    continue

                # --- 分類邏輯 (郵遞區號優先) ---
                check_str = (region + raw_add + name).replace("臺", "台")
                final_city = "其他"
                
                if zip_code.startswith("1"):
                    final_city = "臺北市"
                elif "新北" in check_str and "新北投" not in check_str:
                    final_city = "新北市"
                elif "台北" in check_str:
                    final_city = "臺北市"
                elif "桃園" in check_str: final_city = "桃園市"
                elif "台中" in check_str: final_city = "臺中市"
                elif "台南" in check_str: final_city = "臺南市"
                elif "高雄" in check_str: final_city = "高雄市"
                else:
                    city_map = {"基隆": "基隆市", "新竹": "新竹市", "苗栗": "苗栗縣", "彰化": "彰化縣", "南投": "南投縣", "雲林": "雲林縣", "嘉義": "嘉義市", "屏東": "屏東縣", "宜蘭": "宜蘭縣", "花蓮": "花蓮縣", "台東": "臺東縣"}
                    for k, v in city_map.items():
                        if k in check_str:
                            final_city = v
                            break
                
                if final_city == "臺北市":
                    stats["taipei_count"] += 1

                all_pois.append({
                    "名稱": name,
                    "縣市": final_city, 
                    "地址": raw_add,
                    "緯度": float(py),
                    "經度": float(px),
                    "郵遞區號": zip_code
                })
            except:
                continue
    except Exception as e:
        st.error(f"資料載入失敗: {e}")

    return pd.DataFrame(all_pois), stats

# 執行載入
poi_df, data_stats = load_all_data()

# --- 2. 介面設計 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市"])

# 診斷資訊
st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ 資料診斷 (V11)")
st.sidebar.write(f"XML 總讀取: {data_stats['total_read']}")
st.sidebar.write(f"座標缺失跳過: {data_stats['skipped_no_coords']}")
st.sidebar.write(f"成功識別臺北市: {data_stats['taipei_count']}")

if st.sidebar.button("🗑️ 清除快取重整"):
    st.cache_data.clear()
    st.rerun()

# --- 3. 地圖與列表 ---
filtered_df = poi_df[poi_df["縣市"] == city_filter]

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader(f"🗺️ {city_filter}地圖")
    # 定位中心點
    geolocator = Nominatim(user_agent="taiwan_kids_v11")
    try:
        loc = geolocator.geocode(target_address)
        center = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
    except:
        center = (25.0478, 121.5170)
    
    m = folium.Map(location=center, zoom_start=13)
    folium.Marker(center, popup="我的位置", icon=folium.Icon(color="red")).add_to(m)
    
    for _, row in filtered_df.head(100).iterrows():
        folium.Marker([row["緯度"], row["經度"]], popup=row["名稱"]).add_to(m)
    st_folium(m, width="100%", height=500, key="map")

with col2:
    st.subheader("📋 景點清單")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["名稱", "地址"]].head(50), hide_index=True)
    else:
        st.warning("查無資料")
