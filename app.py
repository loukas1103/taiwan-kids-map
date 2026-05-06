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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖-修復版")

# --- 2. 資料清洗與標準化 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

    # A. 抓取政府資料
    try:
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                reg = info.find('Region').text.strip() if info.find('Region') is not None else ""
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else ""
                
                # 統一轉換地址中的台/臺
                full_add = (reg + add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                # 強化縣市判斷
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in full_add or c in reg:
                        found_city = c
                        break
                
                px = info.find('Px').text # 經度
                py = info.find('Py').text # 緯度
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": found_city,
                        "緯度": float(py),
                        "經度": float(px),
                        "介紹": desc[:200] + "..." if len(desc) > 200 else desc,
                        "來源": "政府公開資料"
                    })
            except: continue
    except Exception as e:
        st.warning(f"政府資料載入中斷: {e}")

    # B. 抓取社群回報資料
    SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_URL)
        if 'lat' in sheet_df.columns: sheet_df.rename(columns={'lat': '緯度'}, inplace=True)
        if 'lng' in sheet_df.columns: sheet_df.rename(columns={'lng': '經度'}, inplace=True)
        
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

# --- 4. 側邊欄與定位 ---
st.sidebar.header("🗺️ 搜尋與導航")

search_query = st.sidebar.text_input("1. 輸入地址/地標自動定位", placeholder="例如：新北市中和區光華街6")
if st.sidebar.button("確認定位"):
    if search_query:
        try:
            gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
            result = gmaps.geocode(search_query, region='tw', language='zh-TW')
            if result:
                loc = result[0]['geometry']['location']
                st.session_state.center_coords = (loc['lat'], loc['lng'])
                st.sidebar.success(f"定位成功：{result[0]['formatted_address']}")
                st.rerun()
        except Exception as e:
            st.sidebar.error(f"Google定位錯誤: {e}")

st.sidebar.markdown("---")
city_list = sorted(list(poi_df['縣市'].unique()))
selected_city = st.sidebar.selectbox("2. 選擇篩選縣市", city_list, index=city_list.index("臺北市") if "臺北市" in city_list else 0)
keyword = st.sidebar.text_input("3. 景點關鍵字搜尋")

# --- 5. 資料處理與距離計算 ---
filtered_df = poi_df[poi_df["縣市"] == selected_city].copy()
if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword.replace("台", "臺"), na=False)]

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 6. 渲染介面 ---
st.title(f"📍 {selected_city} 親子旅遊地圖")

m = folium.Map(location=st.session_state.center_coords, zoom_start=14, control_scale=True)
folium.Marker(st.session_state.center_coords, popup="我的中心點", icon=folium.Icon(color="red", icon="star")).add_to(m)

for _, row in filtered_df.iterrows():
    color = "blue" if row["來源"] == "政府公開資料" else "green"
    folium.Marker(
        location=[row["緯度"], row["經度"]],
        popup=folium.Popup(f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']}km<br>{row['介紹']}", max_width=300),
        tooltip=row["名稱"],
        icon=folium.Icon(color=color, icon="info-sign")
    ).add_to(m)

# 修正處：改用較穩定的邏輯拆解，避免 SyntaxError
map_data = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])

if map_data is not None:
    last_clicked = map_data.get("last_clicked")
    if last_clicked is not None:
        new_lat = last_clicked.get("lat")
        new_lng = last_clicked.get("lng")
        if (new_lat, new_lng) != st.session_state.center_coords:
            st.session_state.center_coords = (new_lat, new_lng)
            st.rerun()

st.subheader("🏠 距離最近的景點 Top 10")
if not filtered_df.empty:
    st.dataframe(filtered_df[["名稱", "距離(km)", "來源", "介紹"]].head(10), use_container_width=True, hide_index=True)
else:
    st.warning("查無符合條件的景點。")
