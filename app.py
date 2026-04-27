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

# --- 1. 初始化快取與 Session State ---
if 'ai_results' not in st.session_state:
    st.session_state.ai_results = []

# 優化：為地址定位加入快取，避免重複請求導致被封鎖或網頁卡頓
@st.cache_data(ttl=86400)
def get_coordinates(address):
    try:
        geolocator = Nominatim(user_agent="taiwan_kids_map_v10")
        loc = geolocator.geocode(address)
        if loc:
            return (loc.latitude, loc.longitude)
    except:
        pass
    return (25.0478, 121.5170) # 預設台北車站

# --- API 金鑰設定 ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"] 
    genai.configure(api_key=GEMINI_API_KEY)
except:
    st.error("請在 Secrets 中設定 GEMINI_API_KEY")

# --- 2. 資料匯入邏輯 (優化快取) ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    # 預定義地名替換表，加速字串處理
    replace_map = {"台北": "臺北", "台中": "臺中", "台南": "臺南", "台東": "臺東"}
    
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        # 優化：設定較短的 timeout 並使用 stream 處理大型 XML (如果有的話)
        response = requests.get(gov_url, timeout=10, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.findtext('Name', "未知景點").strip()
                reg_text = info.findtext('Region', "")
                add_text = info.findtext('Add', "")
                
                geo_combined = reg_text + add_text
                for k, v in replace_map.items():
                    geo_combined = geo_combined.replace(k, v)

                px = info.findtext('Px')
                py = info.findtext('Py')
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": geo_combined[:3], # 假設前三個字通常是縣市
                        "緯度": float(py),
                        "經度": float(px),
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # Google 表單部分
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        if '縣市' in sheet_df.columns:
            for k, v in replace_map.items():
                sheet_df['縣市'] = sheet_df['縣市'].str.replace(k, v)
            sheet_df['來源'] = "社群回報資料"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df[['緯度', '經度']] = df[['緯度', '經度']].apply(pd.to_numeric, errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 3. AI 擴充景點邏輯 ---
def get_ai_recommendations(city, keyword, center_coords):
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = f"..." # 您的 Prompt
        
        response = model.generate_content(
            prompt,
            # 強制要求 JSON 輸出模式
            generation_config={"response_mime_type": "application/json"}
        )
        
        # 移除可能干擾解析的空白或特殊字元
        clean_text = response.text.strip()
        ai_data = json.loads(clean_text)
        
        # ... 後續距離過濾邏輯
    except Exception as e:
        # 在開發階段，建議把 e 印出來看看具體錯誤是什麼
        st.sidebar.error(f"AI 搜尋出錯內容：{str(e)}") 
        return []

# --- 4. 主介面邏輯 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
TAIWAN_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣"]
city_filter = st.sidebar.selectbox("2. 選擇縣市", TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")
use_ai = st.sidebar.checkbox("✨ 啟用 AI 擴充搜尋")

# 獲取位置 (使用快取函數)
center_coords = get_coordinates(target_address)

# 獲取基礎資料並過濾 (優化：僅對目標縣市運算)
poi_df = load_base_data()
filtered_df = poi_df[poi_df["縣市"].str.contains(city_filter[:2])].copy()

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# AI 行為邏輯
if use_ai and st.sidebar.button("開始 AI 尋找景點"):
    with st.spinner("AI 快速搜尋中..."):
        st.session_state.ai_results = get_ai_recommendations(city_filter, keyword, center_coords)
        if st.session_state.ai_results:
            st.rerun()

# 決定顯示資料集
if use_ai and st.session_state.ai_results:
    final_df = pd.DataFrame(st.session_state.ai_results)
else:
    final_df = filtered_df.copy()

# 優化：僅在 Dataframe 不為空且有必要時計算距離
if not final_df.empty:
    # 預先計算距離以供排序與呈現
    final_df["距離(km)"] = final_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    final_df = final_df.sort_values("距離(km)").head(50) # 限制地圖圖釘數量提升渲染速度

# 清除按鈕
if st.session_state.ai_results:
    if st.sidebar.button("🗑️ 清除 AI 結果"):
        st.session_state.ai_results = []
        st.rerun()

# --- 5. 頁面呈現 ---
st.title(f"📍 {city_filter} 親子旅遊查詢")

col1, col2 = st.columns([2, 1])

with col1:
    m = folium.Map(location=center_coords, zoom_start=14, prefer_canvas=True) # prefer_canvas 提升大量點位渲染效能
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red", icon="home")).add_to(m)
    
    if use_ai and st.session_state.ai_results:
        folium.Circle(radius=2000, location=center_coords, color="crimson", fill=True, fill_opacity=0.1).add_to(m)
    
    # 批次加入標記
    for _, row in final_df.iterrows():
        color = "orange" if row["來源"] == "AI 智慧推薦" else "blue"
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=f"{row['名稱']} ({row['距離(km)']}km)",
            icon=folium.Icon(color=color, icon="info-sign")
        ).add_to(m)
    
    st_folium(m, width="100%", height=600, key="map_output")

with col2:
    st.subheader("📋 景點清單")
    if not final_df.empty:
        st.dataframe(final_df[["名稱", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.info("無相符資料。")
