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
st.set_page_config(layout="wide", page_title="台灣景點定位地圖")

# --- 1. 資料匯入與快取 (不變) ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    STANDARD_CITIES = [
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
        "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
        "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
        "臺東縣", "澎湖縣", "金門縣", "連江縣"
    ]

    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else "暫無介紹內容。"
                reg_node = info.find('Region')
                add_node = info.find('Add')
                reg_text = reg_node.text.strip() if reg_node is not None and reg_node.text else ""
                add_text = add_node.text.strip() if add_node is not None and add_node.text else ""
                geo_combined = (reg_text + add_text).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in geo_combined:
                        found_city = c
                        break
                
                px = info.find('Px').text if info.find('Px') is not None else None
                py = info.find('Py').text if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "緯度": float(py),
                        "經度": float(px),
                        "介紹": desc,
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.error(f"資料讀取失敗: {e}")

    # 社群資料
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
            if '介紹' not in sheet_df.columns:
                sheet_df['介紹'] = "社群推薦親子景點。"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 2. 地址精確定位功能 ---
@st.cache_data(ttl=86400)
def get_coords_from_address(address):
    """將地址轉換為經緯度"""
    if not address or address.strip() == "":
        return (25.0478, 121.5170) # 預設台北車站
    
    geolocator = Nominatim(user_agent="taiwan_address_locator_v3")
    try:
        # 優化搜尋詞：確保搜尋範圍在台灣
        clean_address = address.replace("台", "臺")
        search_query = f"{clean_address}, Taiwan"
        
        location = geolocator.geocode(search_query, timeout=10)
        if location:
            return (location.latitude, location.longitude)
        
        # 二次嘗試：原始地址搜尋
        location = geolocator.geocode(clean_address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        st.error(f"定位服務異常: {e}")
    
    return None

# --- 3. 介面設計 ---
st.sidebar.header("📍 定位中心點")
# 改為更直觀的地址輸入
user_input_address = st.sidebar.text_input("輸入完整地址或地標", "台北車站", help="例如：台北市信義區五段7號 或 勤美誠品")

# 執行地址解析
center_coords = get_coords_from_address(user_input_address)

# 若定位失敗處理
if center_coords is None:
    st.sidebar.error(f"❌ 找不到地址：'{user_input_address}'")
    st.sidebar.info("💡 建議：請輸入包含縣市的完整地址，例如「桃園市中壢區...」")
    center_coords = (25.0478, 121.5170) # 定位失敗則停留在台北車站
else:
    st.sidebar.success(f"✅ 已定位：{user_input_address}")

st.sidebar.markdown("---")
st.sidebar.header("🔍 篩選景點")
TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("選擇顯示縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("景點名稱關鍵字")

# 載入資料
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword.replace("台", "臺"), na=False)]

# 計算距離 (以解析出來的地址座標為準)
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. 地圖渲染 ---
st.title("🗺️ 台灣景點地址定位搜尋")
st.info(f"📍 中心點：{user_input_address} (經緯度: {center_coords[0]:.5f}, {center_coords[1]:.5f})")

# 建立地圖 (使用 key 確保地址變更時地圖中心會跳轉)
m = folium.Map(location=center_coords, zoom_start=15, control_scale=True)

# 標記地址中心點
folium.Marker(
    center_coords, 
    popup=f"我的目標地址：{user_input_address}", 
    icon=folium.Icon(color="red", icon="star"),
    tooltip="中心定位點"
).add_to(m)

# 繪製半徑 1km 圈圈 (視覺參考)
folium.Circle(
    radius=1000,
    location=center_coords,
    color="blue",
    fill=True,
    fill_opacity=0.1
).add_to(m)

# 標記景點
for _, row in filtered_df.iterrows():
    color = "blue" if row["來源"] == "政府公開資料" else "green"
    popup_text = f"<b>{row['名稱']}</b><br>距離中心：{row['距離(km)']} km<br><hr>{row['介紹']}"
    
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=folium.Popup(popup_text, max_width=250),
        icon=folium.Icon(color=color, icon="info-sign"),
        tooltip=f"{row['名稱']} ({row['距離(km)']}km)"
    ).add_to(m)

# 渲染地圖，透過 key 綁定地址，地址一改地圖就重繪
st_folium(m, width="100%", height=700, key=f"map_{user_input_address}")

# 數據列表
with st.expander("查看此區域景點列表"):
    st.dataframe(filtered_df[["名稱", "距離(km)", "來源", "介紹"]], use_container_width=True)
