import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
import json
import google.generativeai as genai
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站 (AI 加強版)")

# 初始化 Session State (用於存放 AI 搜尋結果，避免重新整理後消失)
if 'ai_results' not in st.session_state:
    st.session_state.ai_results = []

# --- API 金鑰設定 ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"] 
    genai.configure(api_key=GEMINI_API_KEY)
except:
    st.error("請在 Secrets 中設定 GEMINI_API_KEY")

# --- 1. 資料匯入與標準化邏輯 ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    STANDARD_CITIES = [
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
        "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
        "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
        "臺東縣", "澎湖縣", "金門縣", "連江縣"
    ]

    # --- 方法 A: 政府 XML 資料 ---
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                
                # 強化版縣市判定：結合 Region 與 Add
                reg_node = info.find('Region')
                add_node = info.find('Add')
                reg_text = reg_node.text.strip() if reg_node is not None and reg_node.text else ""
                add_text = add_node.text.strip() if add_node is not None and add_node.text else ""
                
                # 合併文字並標準化
                geo_combined = (reg_text + add_text).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in geo_combined:
                        found_city = c
                        break
                
                # 針對臺北市的特別補救 (若只有 "臺北" 兩個字)
                if found_city == "其他" and "臺北" in geo_combined:
                    found_city = "臺北市"

                px = info.find('Px').text if info.find('Px') is not None else None
                py = info.find('Py').text if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "介紹": info.find('Description').text[:100] if info.find('Description') is not None and info.find('Description').text else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px),
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # --- 方法 B: Google 表單 CSV ---
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning(f"表單讀取失敗: {e}")

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 2. AI 擴充景點邏輯 ---
def get_ai_recommendations(city, keyword):
    model = genai.GenerativeModel('gemini-1.5-flash') # 使用 flash 模型反應較快
    prompt = f"""
    你是一個台灣旅遊專家。請推薦 5 個位於 {city} 的親子旅遊景點，
    關鍵字為 '{keyword}'。
    請嚴格以 JSON 列表格式輸出，包含：名稱, 縣市, 介紹, 緯度, 經度。
    不要輸出任何解釋文字。
    範例：[{"名稱": "測試", "縣市": "{city}", "介紹": "好玩", "緯度": 25.03, "經度": 121.5}]
    """
    try:
        response = model.generate_content(prompt)
        json_str = response.text.replace("```json", "").replace("```", "").strip()
        ai_data = json.loads(json_str)
        for item in ai_data:
            item['來源'] = "AI 智慧推薦"
        return ai_data
    except Exception as e:
        st.error(f"AI 產生失敗: {e}")
        return []

# --- 3. 搜尋介面 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")
use_ai = st.sidebar.checkbox("✨ 啟用 AI 擴充搜尋")

# 定位座標
geolocator = Nominatim(user_agent="taiwan_kids_map_v6")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 載入與篩選基礎資料
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# AI 搜尋按鈕邏輯
if use_ai:
    if st.sidebar.button("開始 AI 尋找景點"):
        with st.spinner("AI 正在發掘隱藏景點..."):
            new_ai_spots = get_ai_recommendations(city_filter, keyword)
            st.session_state.ai_results = new_ai_spots # 存入 Session State

# 合併 AI 資料（如果 Session State 裡有資料）
if st.session_state.ai_results:
    ai_df = pd.DataFrame(st.session_state.ai_results)
    # 確保合併前 AI 資料符合當前縣市與關鍵字篩選 (選擇性)
    filtered_df = pd.concat([filtered_df, ai_df], ignore_index=True)

# 清除 AI 結果按鈕
if st.session_state.ai_results:
    if st.sidebar.button("清除 AI 搜尋結果"):
        st.session_state.ai_results = []
        st.rerun()

# 計算距離並排序
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 4. 顯示結果 ---
st.title(f"📍 {city_filter} 親子旅遊查詢")

col_map, col_info = st.columns([2, 1])
with col_map:
    m = folium.Map(location=center_coords, zoom_start=13)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    color_map = {"政府公開資料": "blue", "社群回報資料": "green", "AI 智慧推薦": "purple"}
    
    for _, row in filtered_df.head(150).iterrows():
        source = row.get("來源", "政府公開資料")
        popup_html = f"<b>{row['名稱']}</b><br>來源: {source}<br>{row.get('介紹', '')}"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color=color_map.get(source, "blue"), icon="info-sign")
        ).add_to(m)
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點清單")
    if not filtered_df.empty:
        st.write(f"目前顯示 {len(filtered_df)} 個景點")
        st.dataframe(filtered_df[["名稱", "距離(km)", "來源"]], use_container_width=True, hide_index=True)
    else:
        st.info("查無資料，請調整條件或嘗試 AI 搜尋。")
