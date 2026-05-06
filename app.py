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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖 (資安強化版)")

# --- 1. 安全讀取 API Key ---
try:
    # 優先從 Streamlit Secrets 讀取
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
except Exception:
    st.error("❌ 未偵測到 GOOGLE_API_KEY。請在 .streamlit/secrets.toml 中設定，或於部署平台上配置 Secrets。")
    st.stop()

# --- 2. 資料匯入與快取 (維持原邏輯) ---
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
        # 政府公開資料
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else "暫無介紹內容。"
                reg_text = info.find('Region').text.strip() if info.find('Region') is not None else ""
                add_text = info.find('Add').text.strip() if info.find('Add') is not None else ""
                
                # 標準化縣市名稱 (台 -> 臺)
                geo_combined = (reg_text + add_text).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in geo_combined:
                        found_city = c
                        break
                
                px = info.find('Px').text
                py = info.find('Py').text
                
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
        st.error(f"政府資料讀取失敗: {e}")

    # 社群回報資料 (Google Sheet)
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

# --- 3. Google Maps API 定位功能 ---
@st.cache_data(ttl=86400)
def get_coordinates_google(address):
    """將地址透過 Google API 轉為經緯度"""
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {
        "address": address,
        "key": GOOGLE_API_KEY,
        "language": "zh-TW"
    }
    try:
        response = requests.get(base_url, params=params)
        data = response.json()
        if data['status'] == 'OK':
            location = data['results'][0]['geometry']['location']
            return (location['lat'], location['lng'])
        else:
            st.sidebar.error(f"Google 定位失敗: {data['status']}")
            
    # 修改這一段來 debug
if data['status'] == 'OK':
    location = data['results'][0]['geometry']['location']
    return (location['lat'], location['lng'])
else:
    # 這裡會顯示 Google 回傳的具體錯誤原因 (error_message)
    error_msg = data.get('error_message', '無具體錯誤原因')
    st.sidebar.error(f"Google 定位失敗: {data['status']}")
    st.sidebar.write(f"詳細原因: {error_msg}")
    
    except Exception as e:
        st.sidebar.error(f"API 連線異常: {e}")
    
    return (25.0478, 121.5170)  # 失敗時回傳台北車站預設值

# --- 4. 介面與搜尋 ---
st.sidebar.header("🔍 親子景點搜尋")
target_address = st.sidebar.text_input("1. 輸入您的中心位置 (地址/地標)", "台北車站")

TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇搜尋縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點名稱關鍵字 (選填)")

# 執行 Google 定位
center_coords = get_coordinates_google(target_address)

# 載入並處理資料
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算與中心點的距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 5. 渲染地圖 ---
st.title(f"📍 {city_filter} 親子旅遊地圖")
st.markdown(f"🚩 目前中心位置：**{target_address}**")

# 建立地圖
m = folium.Map(location=center_coords, zoom_start=14, control_scale=True)

# 標記搜尋中心點
folium.Marker(
    center_coords, 
    popup=f"搜尋中心: {target_address}", 
    icon=folium.Icon(color="red", icon="home")
).add_to(m)

# 繪製 2KM 搜尋範圍圈
folium.Circle(
    radius=2000,
    location=center_coords,
    color="crimson",
    fill=True,
    fill_color="crimson",
    fill_opacity=0.05
).add_to(m)

# 標記景點圖釘
for _, row in filtered_df.iterrows():
    pin_color = "blue" if row["來源"] == "政府公開資料" else "green"
    
    popup_html = f"""
    <div style="width: 250px; font-family: sans-serif;">
        <h4 style="margin-bottom: 5px; color: #1f77b4;">{row['名稱']}</h4>
        <p style="margin: 0; font-size: 0.9em; color: #555;"><b>距離：</b>{row['距離(km)']} km</p>
        <hr style="margin: 10px 0;">
        <div style="max-height: 150px; overflow-y: auto; font-size: 0.85em; line-height: 1.4;">
            {row['介紹']}
        </div>
    </div>
    """
    
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=folium.Popup(popup_html, max_width=300),
        icon=folium.Icon(color=pin_color, icon="info-sign"),
        tooltip=row['名稱']
    ).add_to(m)

# 顯示地圖
st_folium(m, width="100%", height=700, returned_objects=[])

st.caption(f"數據概況：符合條件的景點共 {len(filtered_df)} 個。")
