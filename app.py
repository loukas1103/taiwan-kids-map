import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import time

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
        st.error(f"政府資料讀取失敗: {e}")

    # 社群回報資料
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

# --- 2. 地理位置獲取 (移除 cache 以確保即時更新) ---
def get_coordinates(address):
    if not address:
        return (25.0478, 121.5170)
    
    geolocator = Nominatim(user_agent="taiwan_kids_map_v12")
    try:
        # 強制加入 "台灣" 關鍵字增加精準度
        search_query = f"{address}, Taiwan"
        loc = geolocator.geocode(search_query)
        if loc:
            return (loc.latitude, loc.longitude)
    except Exception as e:
        st.sidebar.warning(f"定位服務忙碌中，請稍後再試：{e}")
    return (25.0478, 121.5170) # 預設台北車站

# --- 3. 介面設計 ---
st.sidebar.header("🔍 景點搜尋與定位")

# 使用 Form 包裹輸入元件，按下按鈕後才觸發更新，防止打字時地圖狂閃
with st.sidebar.form("search_form"):
    target_address = st.text_input("1. 輸入您的中心位置 (或地標)", "台北車站")
    
    TAIWAN_CITIES = ["全部縣市", "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
    city_filter = st.selectbox("2. 過濾特定縣市", TAIWAN_CITIES)
    
    keyword = st.text_input("3. 景點名稱關鍵字")
    
    search_radius = st.slider("4. 搜尋半徑 (km)", 1, 50, 10)
    
    submit_button = st.form_submit_button("更新地圖定位")

# --- 4. 邏輯運算 ---
# 獲取中心座標
center_coords = get_coordinates(target_address)

# 載入資料
poi_df = load_base_data()

# 篩選邏輯
filtered_df = poi_df.copy()

# A. 縣市篩選 (若選全部則不濾)
if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

# B. 關鍵字篩選
if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# C. 距離計算與半徑過濾
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    # 只顯示半徑內的景點
    filtered_df = filtered_df[filtered_df["距離(km)"] <= search_radius]
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 5. 地圖渲染 ---
st.title(f"📍 親子旅遊地圖：{target_address} 附近")
st.markdown(f"目前顯示中心點 {search_radius} 公里內共 **{len(filtered_df)}** 個景點。")

# 建立地圖
m = folium.Map(location=center_coords, zoom_start=13, control_scale=True)

# 標記中心位置
folium.Marker(
    center_coords, 
    popup=f"您的中心點: {target_address}", 
    icon=folium.Icon(color="red", icon="home"),
    tooltip="我的位置"
).add_to(m)

# 繪製搜尋半徑視覺圈
folium.Circle(
    radius=search_radius * 1000,
    location=center_coords,
    color="blue",
    fill=True,
    fill_color="blue",
    fill_opacity=0.05
).add_to(m)

# 標記景點
for _, row in filtered_df.iterrows():
    pin_color = "cadetblue" if row["來源"] == "政府公開資料" else "green"
    
    popup_html = f"""
    <div style="width: 250px; font-family: sans-serif;">
        <h4 style="margin-bottom: 5px; color: #1f77b4;">{row['名稱']}</h4>
        <p style="margin: 0; font-size: 0.9em; color: #555;"><b>距離中心：</b>{row['距離(km)']} km</p>
        <p style="margin: 0; font-size: 0.9em; color: #555;"><b>所屬縣市：</b>{row['縣市']}</p>
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
st_folium(m, width="100%", height=700, key="main_map")

# 顯示資料列表 (選配，方便使用者直接看距離)
with st.expander("查看景點清單"):
    st.dataframe(filtered_df[["名稱", "縣市", "距離(km)", "來源"]], use_container_width=True)
