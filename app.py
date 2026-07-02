import streamlit as st
import pandas as pd
import folium
import json
import os
import urllib3
import googlemaps
from streamlit_folium import st_folium
from geopy.distance import geodesic

# 消除必要的 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 安全讀取 API Key ---
def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    else:
        st.error("❌ 找不到 Google API Key！請在 Streamlit Cloud 的 Secrets 中設定。")
        st.stop()

GOOGLE_MAPS_API_KEY = get_google_api_key()

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖")

# --- 2. 資料清洗與標準化 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

    # A. 讀取本地新版政府 JSON 資料 (使用絕對路徑定位防錯)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    json_filename = os.path.join(current_dir, "AttractionList.json")
    
    if os.path.exists(json_filename):
        try:
            with open(json_filename, 'r', encoding='utf-8') as f:
                raw_data = json.load(f)
                
            # 依據新版結構，景點資料存放在 "Attractions" 鍵值中
            data_list = raw_data.get("Attractions", [])
                
            for item in data_list:
                try:
                    # 1. 安全取得經緯度，避免 KeyError 崩潰
                    px_val = item.get('PositionLon', None)
                    py_val = item.get('PositionLat', None)
                    
                    if px_val is None or py_val is None or px_val == "" or py_val == "":
                        continue
                        
                    px = float(px_val)
                    py = float(py_val)
                    
                    # 2. 處理景點名稱
                    name = item.get('AttractionName', '')
                    name = name.strip() if isinstance(name, str) else "未知景點"
                    
                    # 3. 處理縣市欄位 (解決 List 階層)
                    city_data = item.get('LocatedCities', '')
                    if isinstance(city_data, list):
                        city_val = "".join(city_data) 
                    else:
                        city_val = str(city_data)
                    city_val = city_val.strip()
                    
                    # 4. 處理地址
                    address = item.get('PostalAddress', '')
                    address = address.strip() if isinstance(address, str) else ""
                    
                    # 5. 統一台/臺並進行縣市判斷
                    search_str = (name + city_val + address).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                    
                    found_city = "其他"
                    for c in STANDARD_CITIES:
                        if c in search_str:
                            found_city = c
                            break
                    
                    # 座標補位判斷 (臺北市範圍)
                    if found_city == "其他" and 24.96 <= py <= 25.21 and 121.45 <= px <= 121.67:
                        found_city = "臺北市"

                    if found_city in STANDARD_CITIES:
                        all_pois.append({
                            "名稱": name, "縣市": found_city, "緯度": py, "經度": px, "來源": "政府公開資料"
                        })
                except: 
                    continue # 單一景點格式有瑕疵直接略過
        except Exception as e:
            st.sidebar.error(f"❌ 本地 JSON 解析失敗: {e}")
    else:
        st.sidebar.warning(f"⚠️ 找不到本地檔案 `AttractionList.json`，請確認是否與 app.py 放在同一個目錄下。")

    # B. 社群回報資料 (保留線上 Google 試算表)
    SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_URL)
        sheet_df.rename(columns={'lat': '緯度', 'lng': '經度'}, inplace=True)
        if '縣市' in sheet_df.columns:
            def clean_city(x):
                x = str(x).replace("台北", "臺北").replace("台中", "臺中")
                for c in STANDARD_CITIES:
                    if c in x: return c
                return "其他"
            sheet_df['縣市'] = sheet_df['縣市'].apply(clean_city)
            sheet_df['來源'] = "社群回報資料"
            
            keep_cols = [c for c in ['名稱', '縣市', '緯度', '經度', '來源'] if c in sheet_df.columns]
            all_pois.extend(sheet_df[keep_cols].to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        df = df[df['縣市'].isin(STANDARD_CITIES)]
    return df

# --- 3. 初始化 Session State ---
if 'center_coords' not in st.session_state:
    st.session_state.center_coords = (25.0478, 121.5170)
if 'selected_city' not in st.session_state:
    st.session_state.selected_city = "臺北市"
if 'keyword' not in st.session_state:
    st.session_state.keyword = ""

poi_df = load_all_data()

# --- 4. 側邊欄：統一搜尋介面 ---
st.sidebar.header("🔍 搜尋控制中心")

input_address = st.sidebar.text_input("1. 定位地址/地標", placeholder="例如：台北101")

if not poi_df.empty:
    city_list = sorted(list(poi_df['縣市'].unique()))
else:
    city_list = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市"]

input_city = st.sidebar.selectbox("2. 選擇縣市", city_list, index=city_list.index(st.session_state.selected_city) if st.session_state.selected_city in city_list else 0)
input_keyword = st.sidebar.text_input("3. 景點關鍵字搜尋", value=st.session_state.keyword)

if st.sidebar.button("🚀 執行搜尋與定位", use_container_width=True):
    st.session_state.selected_city = input_city
    st.session_state.keyword = input_keyword
    
    if input_address:
        try:
            gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
            result = gmaps.geocode(input_address, region='tw', language='zh-TW')
            if result:
                loc = result[0]['geometry']['location']
                st.session_state.center_coords = (loc['lat'], loc['lng'])
                st.sidebar.success("定位成功！")
            else:
                st.sidebar.error("找不到該地址。")
        except Exception as e:
            st.sidebar.error(f"Google定位錯誤: {e}")
    st.rerun()

# --- 5. 資料篩選與距離計算 ---
filtered_df = pd.DataFrame()
if not poi_df.empty:
    filtered_df = poi_df[poi_df["縣市"] == st.session_state.selected_city].copy()
    if st.session_state.keyword:
        k = st.session_state.keyword.replace("台", "臺")
        filtered_df = filtered_df[filtered_df["名稱"].str.contains(k, na=False)]

    if not filtered_df.empty:
        filtered_df["距離(km)"] = filtered_df.apply(
            lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
        )
        filtered_df = filtered_df.sort_values("距離(km)")

# --- 6. 地圖呈現 ---
st.title(f"📍 {st.session_state.selected_city} 親子旅遊地圖")

m = folium.Map(location=st.session_state.center_coords, zoom_start=15, control_scale=True)

# 定位中心點
folium.Marker(
    st.session_state.center_coords, 
    popup="<b>📍 我的定位中心</b>", 
    tooltip="目前定位點",
    icon=folium.Icon(color="red", icon="star", prefix="fa")
).add_to(m)

# 標記景點圖釘
if not filtered_df.empty:
    for _, row in filtered_df.iterrows():
        icon_color = "green" if row["來源"] == "社群回報資料" else "blue"
        
        popup_html = f"""
        <div style='width:200px; font-family: sans-serif;'>
            <h4 style='margin-bottom:5px; color:#1f77b4;'>{row['名稱']}</h4>
            <p style='margin:2px 0;'><b>📏 距離中心：</b>{row['距離(km)']} km</p>
            <p style='margin:2px 0;'><b>🏷️ 來源：</b>{row['來源']}</p>
        </div>
        """
        
        folium.Marker(
            location=[row["緯度"], row["經度"]],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=row["名稱"],
            icon=folium.Icon(color=icon_color, icon="info-sign")
        ).add_to(m)

# 渲染地圖
st_folium(m, width="100%", height=750, returned_objects=[])

if filtered_df.empty:
