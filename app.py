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
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖-優化整合版")

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
                add = info.find('Add').text.strip() if info.find('Add') is not None and info.find('Add').text else ""
                reg = info.find('Region').text.strip() if info.find('Region') is not None and info.find('Region').text else ""
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else ""
                
                px_val = info.find('Px').text
                py_val = info.find('Py').text
                
                if px_val and py_val:
                    px = float(px_val)
                    py = float(py_val)
                    
                    search_str = (name + reg + add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                    
                    found_city = "其他"
                    for c in STANDARD_CITIES:
                        if c in search_str:
                            found_city = c
                            break
                    
                    # 座標補位判斷
                    if found_city == "其他":
                        if 24.96 <= py <= 25.21 and 121.45 <= px <= 121.67:
                            found_city = "臺北市"

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

    # B. 社群回報資料
    SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_URL)
        sheet_df.rename(columns={'lat': '緯度', 'lng': '經度'}, inplace=True)
        if '縣市' in sheet_df.columns:
            # 修正：確保縣市欄位只保留標準名稱，避免出現地址
            def clean_city(x):
                x = str(x).replace("台北", "臺北").replace("台中", "臺中")
                for c in STANDARD_CITIES:
                    if c in x: return c
                return "其他"
            
            sheet_df['縣市'] = sheet_df['縣市'].apply(clean_city)
            sheet_df['來源'] = "社群回報資料"
            all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        # 修正問題 1：過濾掉非標準縣市的異常字串
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

# 輸入控制項
input_address = st.sidebar.text_input("1. 定位地址/地標", placeholder="例如：新北市中和區光華街6")
city_list = sorted(list(poi_df['縣市'].unique()))
input_city = st.sidebar.selectbox("2. 選擇縣市", city_list, index=city_list.index(st.session_state.selected_city) if st.session_state.selected_city in city_list else 0)
input_keyword = st.sidebar.text_input("3. 景點關鍵字搜尋", value=st.session_state.keyword)

# 修正問題 4：統一搜尋按鈕
if st.sidebar.button("🚀 執行搜尋與定位", use_container_width=True):
    # 更新關鍵字與城市
    st.session_state.selected_city = input_city
    st.session_state.keyword = input_keyword
    
    # 執行地址定位
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

st.sidebar.markdown("---")
if st.sidebar.button("🔄 回到預設中心 (台北車站)"):
    st.session_state.center_coords = (25.0478, 121.5170)
    st.rerun()

# --- 5. 資料篩選與計算 ---
filtered_df = poi_df[poi_df["縣市"] == st.session_state.selected_city].copy()

# 關鍵字過濾
if st.session_state.keyword:
    k = st.session_state.keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(k, na=False)]

# 距離計算
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 6. 地圖呈現 ---
st.title(f"親子旅遊地圖 - {st.session_state.selected_city}")
st.caption(f"中心點座標: {st.session_state.center_coords}")

m = folium.Map(location=st.session_state.center_coords, zoom_start=14, control_scale=True)
folium.Marker(st.session_state.center_coords, popup="我的中心點", icon=folium.Icon(color="red", icon="star")).add_to(m)

# 標記景點
for _, row in filtered_df.iterrows():
    # 修正問題 2：社群資料以綠色標示
    icon_color = "green" if row["來源"] == "社群回報資料" else "blue"
    
    folium.Marker(
        location=[row["緯度"], row["經度"]],
        popup=folium.Popup(f"<b>{row['名稱']}</b><br>來源: {row['來源']}<br>距離: {row['距離(km)']}km", max_width=300),
        tooltip=row["名稱"],
        icon=folium.Icon(color=icon_color, icon="info-sign")
    ).add_to(m)

map_data = st_folium(m, width="100%", height=550, returned_objects=["last_clicked"])

# 處理點擊地圖更換中心
if map_data and map_data.get("last_clicked"):
    clicked = map_data["last_clicked"]
    new_p = (clicked["lat"], clicked["lng"])
    if new_p != st.session_state.center_coords:
        st.session_state.center_coords = new_p
        st.rerun()

# 顯示推薦清單
st.subheader("🏠 附近推薦景點")
if not filtered_df.empty:
    st.dataframe(filtered_df[["名稱", "距離(km)", "來源", "介紹"]].head(15), use_container_width=True, hide_index=True)
else:
    st.warning("查無符合條件的景點，請嘗試修改關鍵字或切換縣市。")
