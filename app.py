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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖")

# --- 1. 資料匯入與快取 ---
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
                reg_text = info.find('Region').text.strip() if info.find('Region') is not None else ""
                add_text = info.find('Add').text.strip() if info.find('Add') is not None else ""
                
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
        st.error(f"政府資料載入失敗: {e}")

    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
            if '介紹' not in sheet_df.columns: sheet_df['介紹'] = "社群推薦親子景點。"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    return pd.DataFrame(all_pois)

# --- 2. 強化定位功能 ---
@st.cache_data(ttl=86400)
def get_coordinates(address):
    # 使用獨特的 User-Agent 避免被 Nominatim 封鎖
    geolocator = Nominatim(user_agent="taiwan_parent_child_map_v2026")
    try:
        # 增加 timeout 處理網路延遲
        location = geolocator.geocode(address, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except Exception as e:
        st.sidebar.warning(f"定位連線異常: {e}")
    
    # 若失敗，嘗試自動補上 "台灣" 關鍵字再試一次
    try:
        location = geolocator.geocode(f"台灣 {address}", timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except:
        pass
        
    return (25.0478, 121.5170) # 最終預設值：台北車站

# --- 3. 側邊欄搜尋與過濾 ---
st.sidebar.header("🔍 地圖定位與搜尋")
target_address = st.sidebar.text_input("1. 輸入您的中心位置", value="台北車站")
TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點名稱關鍵字")

# 獲取中心座標 (含錯誤處理機制)
center_coords = get_coordinates(target_address)

# 載入資料
df = load_base_data()

# 資料篩選
if not df.empty:
    mask = (df["縣市"] == city_filter)
    if keyword:
        mask &= (df["名稱"].str.contains(keyword.replace("台", "臺"), na=False))
    
    filtered_df = df[mask].copy()
    
    # 計算距離
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")
else:
    filtered_df = pd.DataFrame()

# --- 4. 渲染地圖 ---
st.title(f"📍 {city_filter} 親子旅遊圖釘地圖")
st.markdown(f"🚩 目前中心點：**{target_address}** (緯度: {center_coords[0]:.4f}, 經度: {center_coords[1]:.4f})")

# 建立地圖
m = folium.Map(location=center_coords, zoom_start=14)

# 中心位置圖釘
folium.Marker(
    center_coords, 
    popup=f"我的位置: {target_address}", 
    icon=folium.Icon(color="red", icon="home")
).add_to(m)

# 2KM 視覺圈
folium.Circle(
    radius=2000, location=center_coords, color="crimson", fill=True, fill_opacity=0.05
).add_to(m)

# 景點圖釘
for _, row in filtered_df.iterrows():
    pin_color = "blue" if row["來源"] == "政府公開資料" else "green"
    
    popup_html = f"""
    <div style="width: 250px; font-family: Microsoft JhengHei, sans-serif;">
        <h4 style="margin-bottom: 5px; color: #1f77b4;">{row['名稱']}</h4>
        <p style="margin: 0; font-size: 0.9em; color: #555;"><b>距離：</b>{row['距離(km)']} km</p>
        <hr style="margin: 8px 0;">
        <div style="max-height: 150px; overflow-y: auto; font-size: 0.85em; line-height: 1.5; color: #333;">
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

# 滿幅顯示地圖
st_folium(m, width="100%", height=750, returned_objects=[])

st.caption(f"共找到 {len(filtered_df)} 個景點。資料來源：交通部觀光署、社群協作。")
