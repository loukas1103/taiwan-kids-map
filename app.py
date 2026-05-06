import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.distance import geodesic

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子地圖 - 偵錯模式")

# --- 1. 安全讀取 API Key ---
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("❌ 未偵測到 Secrets 設定。請檢查 .streamlit/secrets.toml 是否包含 GOOGLE_API_KEY")
    st.stop()

# --- 2. 資料匯入快取 ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知"
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else ""
                reg = info.find('Region').text.strip() if info.find('Region') is not None else ""
                add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                geo_combined = (reg + add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in geo_combined:
                        found_city = c
                        break
                px = info.find('Px').text
                py = info.find('Py').text
                if px and py:
                    all_pois.append({"名稱": name, "縣市": found_city, "緯度": float(py), "經度": float(px), "介紹": desc, "來源": "政府資料"})
            except: continue
    except Exception as e:
        st.error(f"資料讀取失敗: {e}")
    return pd.DataFrame(all_pois)

# --- 3. 強化偵錯功能的定位函數 ---
@st.cache_data(ttl=86400)
def get_coordinates_with_debug(address):
    """將地址轉座標，並在失敗時抓取完整錯誤詳細資訊"""
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": GOOGLE_API_KEY,
        "language": "zh-TW"
    }
    
    debug_info = {"status": "Unknown", "error_message": "無內容"}
    
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        status = data.get('status')
        
        if status == 'OK':
            loc = data['results'][0]['geometry']['location']
            return (loc['lat'], loc['lng']), None
        else:
            # 抓取 Google 回傳的具體錯誤說明
            debug_info["status"] = status
            debug_info["error_message"] = data.get('error_message', 'Google 未提供具體錯誤文字')
            return (25.0478, 121.5170), debug_info
            
    except Exception as e:
        debug_info["status"] = "Python_Exception"
        debug_info["error_message"] = str(e)
        return (25.0478, 121.5170), debug_info

# --- 4. 介面與邏輯 ---
st.sidebar.header("🔍 搜尋設定")
target_address = st.sidebar.text_input("1. 輸入中心位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "宜蘭縣", "花蓮縣"])

# 執行定位並獲取偵錯資訊
center_coords, error_report = get_coordinates_with_debug(target_address)

# 如果有錯誤，顯示在側邊欄顯眼處
if error_report:
    st.sidebar.error(f"⚠️ 定位失敗：{error_report['status']}")
    with st.sidebar.expander("查看完整錯誤原因 (Debug)"):
        st.write(f"**狀態碼:** {error_report['status']}")
        st.write(f"**詳細訊息:** {error_report['error_message']}")
        st.info("💡 提示：若是 REQUEST_DENIED，通常是 API 未啟用或金鑰限制設定錯誤。")

# 篩選資料
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1)
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 5. 地圖呈現 ---
st.title("📍 親子旅遊地圖系統")
m = folium.Map(location=center_coords, zoom_start=14)

folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)

for _, row in filtered_df.iterrows():
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']}km",
        tooltip=row['名稱']
    ).add_to(m)

st_folium(m, width="100%", height=700, returned_objects=[])
