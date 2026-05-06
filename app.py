import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
import googlemaps
from streamlit_folium import st_folium
from geopy.distance import geodesic

# 消除必要的 SSL 警告 (政府資料來源可能憑證不全)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 1. 資安強化：從 Streamlit Secrets 讀取 API Key ---
# 這在 GitHub 部署到 Streamlit Cloud 時是標準作法
def get_google_api_key():
    if "GOOGLE_MAPS_API_KEY" in st.secrets:
        return st.secrets["GOOGLE_MAPS_API_KEY"]
    else:
        st.error("❌ 找不到 Google API Key！")
        st.info("請在 Streamlit Cloud 控制台的 Settings > Secrets 中設定 GOOGLE_MAPS_API_KEY。")
        st.stop()

GOOGLE_MAPS_API_KEY = get_google_api_key()

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊地圖-雲端資安版")

# --- 2. 高效率資料載入與過濾 ---
@st.cache_data(ttl=3600)
def load_base_data():
    all_pois = []
    STANDARD_CITIES = ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "臺東縣", "澎湖縣", "金門縣", "連江縣"]

    try:
        # 政府資料 (Timeout 設定為 10 秒以維護系統穩定)
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=10, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                reg = info.find('Region').text.strip() if info.find('Region') is not None else ""
                desc = info.find('Toldescribe').text.strip() if info.find('Toldescribe') is not None else "暫無介紹。"
                
                full_add = (reg + add).replace("台北", "臺北").replace("台中", "臺中").replace("台南", "臺南").replace("台東", "臺東")
                
                found_city = "其他"
                for c in STANDARD_CITIES:
                    if c in full_add:
                        found_city = c
                        break
                
                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name, "縣市": found_city, "緯度": float(py), "經度": float(px),
                        "介紹": desc[:150], "來源": "政府公開資料"
                    })
            except: continue
    except:
        st.warning("無法連線至政府 API，僅顯示社群資料。")

    # 社群回報資料
    SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_URL)
        if '縣市' in sheet_df.columns:
            sheet_df['縣市'] = sheet_df['縣市'].astype(str).str.replace("台北", "臺北").str.replace("台中", "臺中")
            sheet_df['來源'] = "社群回報資料"
        all_pois.extend(sheet_df.to_dict('records'))
    except: pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 3. 初始化 Session State ---
if 'center_coords' not in st.session_state:
    st.session_state.center_coords = (25.0478, 121.5170)

# --- 4. 側邊欄邏輯 ---
st.sidebar.header("🗺️ 導航與篩選")

# 地址搜尋 (使用 Google Geocoding)
search_query = st.sidebar.text_input("1. 輸入地址或地標自動定位", placeholder="例如：新北市中和區光華街6")

if st.sidebar.button("確認定位"):
    if search_query:
        with st.spinner("Google 搜尋中..."):
            try:
                gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)
                result = gmaps.geocode(search_query, region='tw', language='zh-TW')
                if result:
                    loc = result[0]['geometry']['location']
                    st.session_state.center_coords = (loc['lat'], loc['lng'])
                    st.sidebar.success(f"已定位：{result[0]['formatted_address']}")
                    st.rerun()
                else:
                    st.sidebar.error("找不到該地址。")
            except Exception as e:
                st.sidebar.error(f"API 錯誤: {e}")

st.sidebar.markdown("---")
city_list = ["宜蘭縣", "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "新竹市", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義市", "嘉義縣", "屏東縣", "花蓮縣", "臺東縣"]
selected_city = st.sidebar.selectbox("2. 選擇篩選縣市", city_list)

# --- 5. 地圖與距離計算 ---
df = load_base_data()
filtered_df = df[df["縣市"] == selected_city].copy()

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(st.session_state.center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 6. 頁面渲染 ---
st.title("📍 全台親子旅遊地圖")
st.caption(f"目前中心座標: {st.session_state.center_coords}")

# 建立地圖
m = folium.Map(location=st.session_state.center_coords, zoom_start=15)
folium.Marker(st.session_state.center_coords, icon=folium.Icon(color='red', icon='star')).add_to(m)

# 標記景點 (限制 30 個提升 GitHub Codespaces 執行流暢度)
for _, row in filtered_df.head(30).iterrows():
    folium.Marker(
        [row["緯度"], row["經度"]],
        popup=f"<b>{row['名稱']}</b><br>距離: {row['距離(km)']}km",
        tooltip=row['名稱']
    ).add_to(m)

# 顯示地圖
map_output = st_folium(m, width="100%", height=500, returned_objects=["last_clicked"])

# 處理點擊地圖更新中心
if map_output and map_output["last_clicked"]:
    new_p = (map_output["last_clicked"]["lat"], map_output["last_clicked"]["lng"])
    if new_p != st.session_state.center_coords:
        st.session_state.center_coords = new_p
        st.rerun()

# 顯示距離最近的前 10 名
st.subheader("🏠 附近推薦景點")
if not filtered_df.empty:
    st.table(filtered_df[["名稱", "距離(km)", "介紹"]].head(10))
else:
    st.info("該縣市目前無景點資料。")
