import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖-邏輯修復版")

# --- 2. 資料清洗與強制歸類邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                add = info.find('Add').text.strip() if info.find('Add') is not None and info.find('Add').text else ""
                reg = info.find('Region').text.strip() if info.find('Region') is not None and info.find('Region').text else ""
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else ""
                
                px_val = info.find('Px').text
                py_val = info.find('Py').text
                
                if px_val and py_val:
                    px = float(px_val)
                    py = float(py_val)
                    
                    # --- 強化判斷邏輯 ---
                    # 結合名稱、區域、地址進行初步判斷
                    search_str = (name + reg + add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                    
                    found_city = "其他"
                    for c in STANDARD_CITIES:
                        if c in search_str:
                            found_city = c
                            break
                    
                    # --- 座標補位判斷 (解決 Add 和 Region 為空的問題) ---
                    # 如果文字判斷不到，但座標在臺北市大致範圍內 (24.96~25.21, 121.45~121.67)
                    if found_city == "其他":
                        if 24.96 <= py <= 25.21 and 121.45 <= px <= 121.67:
                            found_city = "臺北市"
                        elif 24.95 <= py <= 25.30 and 121.28 <= px <= 121.60:
                            # 簡單示範：這範圍大致是新北市
                            found_city = "新北市"

                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city,
                        "緯度": py,
                        "經度": px,
                        "介紹": desc[:200] + "..." if len(desc) > 200 else desc,
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.warning(f"政府資料載入中斷: {e}")

    # B. 社群資料 (欄位名稱標準化)
    SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_URL)
        sheet_df.rename(columns={'lat': '緯度', 'lng': '經度', '經度': '經度', '緯度': '緯度'}, inplace=True)
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

# --- 3. 初始化 ---
if 'center_coords' not in st.session_state:
    st.session_state.center_coords = (25.0478, 121.5170)

poi_df = load_all_data()

# --- 4. 側邊欄 ---
st.sidebar.header("🗺️ 搜尋與導航")
search_query = st.sidebar.text_input("1. 輸入地址/地標自動定位", placeholder="例如：台北火車站、台北市大安區...")
if st.sidebar.button("確認定位"):
    if search_query:
        try:
            gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
            result = gmaps.geocode(search_query, region='tw', language='zh-TW')
            if result:
                loc = result[0]['geometry']['location']
                st.session_state.center_coords = (loc['lat'], loc['lng'])
                st.sidebar.success("定位成功！")
                st.rerun()
        except Exception as e:
            st.sidebar.error(f"Google定位錯誤: {e}")

st.sidebar.markdown("---")
# 確保選單顯示「臺北市」
city_list = sorted([c for c in poi_df['縣市'].unique() if c != "其他"])
if "臺北市" not in city_list: city_list.append("臺北市")
selected_city = st.sidebar.selectbox("2. 選擇篩選縣市", sorted(city_list), index=city_list.index("臺北市") if "臺北市" in city_list else 0)

# --- 5. 計算距離與過濾 ---
filtered_df = poi_df[poi_df["縣市"] == selected_city].copy()
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 6. 介面 ---
st.title(f"📍 {selected_city} 親子旅遊地圖")
m = folium.Map(location=st.session_state.center_coords, zoom_start=14)
folium.Marker(st.session_state.center_coords, icon=folium.Icon(color="red", icon="star")).add_to(m)

for _, row in filtered_df.iterrows():
    folium.Marker(
        location=[row["緯度"], row["經度"]],
        popup=f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']}km",
        tooltip=row["名稱"],
        icon=folium.Icon(color="blue", icon="info-sign")
    ).add_to(m)

map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])

if map_data and map_data.get("last_clicked"):
    new_p = (map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"])
    if new_p != st.session_state.center_coords:
        st.session_state.center_coords = new_p
        st.rerun()

st.dataframe(filtered_df[["名稱", "距離(km)", "介紹"]].head(20), use_container_width=True, hide_index=True)
