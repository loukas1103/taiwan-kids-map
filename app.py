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

# 初始化 Session State
if 'ai_results' not in st.session_state:
    st.session_state.ai_results = []

# --- API 金鑰設定 ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"] 
    genai.configure(api_key=GEMINI_API_KEY)
except:
    st.error("請在 Secrets 中設定 GEMINI_API_KEY")

# --- 1. 資料匯入邏輯 ---
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
                
                if found_city == "其他" and "臺北" in geo_combined:
                    found_city = "臺北市"

                px = info.find('Px').text if info.find('Px') is not None else None
                py = info.find('Py').text if info.find('Py') is not None else None
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city, 
                        "緯度": float(py),
                        "經度": float(px),
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 2. AI 擴充景點邏輯 ---
def get_ai_recommendations(city, keyword):
    try:
        # 使用最新的 Gemini 2.5 Flash 模型
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        
        prompt = f"""
        你是一個台灣旅遊專家。請推薦 5 個位於 {city} 的親子旅遊景點，
        關鍵字必須包含 '{keyword}'。
        請嚴格以 JSON 列表格式輸出，不要包含任何解釋文字。
        物件包含：名稱, 縣市, 緯度, 經度。
        範例格式：
        [
          {{"名稱": "景點名", "縣市": "{city}", "緯度": 25.0, "經度": 121.0}}
        ]
        """
        
        response = model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        
        ai_data = json.loads(response.text)
        for item in ai_data:
            item['來源'] = "AI 智慧推薦"
        return ai_data

    except Exception as e:
        st.sidebar.error(f"AI 搜尋出錯：{str(e)}")
        return []

# --- 3. 介面與邏輯 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")
use_ai = st.sidebar.checkbox("✨ 啟用 AI 擴充搜尋")

# 定位我的位置
geolocator = Nominatim(user_agent="taiwan_kids_map_v8")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 載入並初步篩選
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"] == city_filter].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# AI 按鈕
if use_ai:
    if st.sidebar.button("開始 AI 尋找景點"):
        with st.spinner("AI 正在為您搜尋最近景點..."):
            res = get_ai_recommendations(city_filter, keyword)
            if res:
                st.session_state.ai_results = res
                st.rerun() # 立即重新整理以載入 AI 資料

# 合併並計算距離
final_df = filtered_df.copy()
if st.session_state.ai_results:
    ai_df = pd.DataFrame(st.session_state.ai_results)
    final_df = pd.concat([final_df, ai_df], ignore_index=True)

if not final_df.empty:
    # 統一計算距離
    final_df["距離(km)"] = final_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    # 距離近者優先排序
    final_df = final_df.sort_values("距離(km)")

# 清除 AI 按鈕
if st.session_state.ai_results:
    if st.sidebar.button("🗑️ 清除 AI 搜尋結果"):
        st.session_state.ai_results = []
        st.rerun()

# --- 4. 渲染頁面 ---
st.title(f"📍 {city_filter} 親子旅遊查詢系統")

col1, col2 = st.columns([2, 1])

with col1:
    m = folium.Map(location=center_coords, zoom_start=13)
    # 我的位置 - 紅色
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    # 標記在地圖上的圖釘
    for _, row in final_df.head(100).iterrows():
        src = row.get("來源", "政府公開資料")
        
        # 依照來源決定圖釘顏色：AI 為黃色(orange)，其他為藍色/綠色
        if src == "AI 智慧推薦":
            pin_color = "orange"
        elif src == "社群回報資料":
            pin_color = "green"
        else:
            pin_color = "blue"
            
        # 圖釘資訊：顯示名稱及距離即可
        popup_content = f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']} km"
        
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_content, max_width=200),
            icon=folium.Icon(color=pin_color, icon="info-sign")
        ).add_to(m)
        
    st_folium(m, width="100%", height=600, key="main_map")

with col2:
    st.subheader("📋 推薦清單 (距離近優先)")
    if not final_df.empty:
        # 清單中刪除來源，僅顯示名稱與距離
        st.dataframe(
            final_df[["名稱", "距離(km)"]], 
            use_container_width=True, 
            hide_index=True
        )
    else:
        st.info("目前的條件下無景點，請調整關鍵字或開啟 AI 搜尋。")
