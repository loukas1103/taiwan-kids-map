import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET # 需在檔案最上方 import
import urllib3 # 需在檔案上方 import，用來消除警告 urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import io

# 設定頁面
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 資料匯入整合邏輯 ---
@st.cache_data(ttl=3600)  # 每小時自動重新抓取一次 (需求 3)
def load_all_data():
    all_pois = []

    # ... 你的 XML 與 Google Sheet CSV 讀取代碼 ...
    # 讀取後轉成 DataFrame
    df = pd.DataFrame(all_pois)

    if not df.empty:
        # 清除欄位名稱可能存在的空格 (重要！)
        df.columns = df.columns.str.strip()
        
        # 強制確認「緯度」與「經度」這兩個欄位存在
        # 如果你的 CSV 裡標題不同 (例如叫 Lat/Lng)，請在此統一改名
        # df = df.rename(columns={'舊名稱': '緯度'}) 

        # 轉換型態
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')

        # 刪除無座標的列
        df = df.dropna(subset=['緯度', '經度'])
        
    return df
    
    # --- 方法 A: 政府資料開放平台 (改為 XML 匯入) ---
    try:
        # 使用觀光署提供的 XML 網址 (範例：全台觀光景點資料)
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        # response = requests.get(gov_url, timeout=15)
        response.encoding = 'utf-8' # 強制設定編碼防止亂碼
        
        # 解析 XML 內容
        root = ET.fromstring(response.content)
        
        # 根據觀光署 XML 結構 (XML_Head -> Infos -> Info)
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text if info.find('Name') is not None else "未知景點"
                address = info.find('Add').text if info.find('Add') is not None else ""
                description = info.find('Description').text if info.find('Description') is not None else "暫無介紹"
                px = info.find('Px').text # 經度
                py = info.find('Py').text # 緯度

                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": address[0:3] if address else "其他",
                        "介紹": description[:100] + "...",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue # 跳過資料不完整的項目
                
        st.success(f"成功從政府平台同步 {len(all_pois)} 筆資料！")

    except Exception as e:
        st.error(f"政府 XML 資料匯入失敗: {e}")

    # --- 方法 B: Google 表單試算表 (需求 2) ---
    # 請將下方網址替換為你「發佈到網路」的 CSV 網址
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        # 確保試算表欄位名稱與程式一致
        all_pois.extend(sheet_df.to_dict('records'))
    except Exception as e:
        st.warning("Google 表單資料暫無數據或連結錯誤。")

    return pd.DataFrame(all_pois)

# 啟動時自動執行匯入
with st.spinner('正在同步最新景點資訊...'):
    poi_df = load_all_data()

# --- 2. 介面設計與搜尋邏輯 (與先前一致) ---
TAIWAN_CITIES = ["台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", "台東縣", "澎湖縣", "金門縣", "連江縣"]

st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 地理定位
geolocator = Nominatim(user_agent="taiwan_kids_travel_v2")
try:
    loc = geolocator.geocode(target_address)
    center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 篩選資料
filtered_df = poi_df.copy()
if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]
if keyword:
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(keyword, na=False)]

# 計算距離
def calc_dist(row):
    try:
        return round(geodesic(center_coords, (row["緯度"], row["經度"])).km, 2)
    except:
        return 9999

if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(calc_dist, axis=1)
    filtered_df = filtered_df.sort_values("距離(km)")
    
# 在顯示地圖的區域
for _, row in filtered_df.iterrows():
    try:
        # 強制轉型為 float
        lat = float(row["緯度"])
        lng = float(row["經度"])
        
        popup_text = f"<b>{row['名稱']}</b><br>{row['介紹']}"
        folium.Marker(
            [lat, lng],
            popup=folium.Popup(popup_text, max_width=250),
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    except (ValueError, TypeError):
        # 如果該列資料無法轉為數字，就跳過不畫
        continue

# --- 3. 畫面顯示 ---
col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("🗺️ 景點地圖")
    m = folium.Map(location=center_coords, zoom_start=12)
    folium.Marker(center_coords, popup="我的位置", icon=folium.Icon(color="red")).add_to(m)
    
if not filtered_df.empty:
    for _, row in filtered_df.iterrows():
        # 加上我們之前的防錯機制：檢查經緯度
        if pd.notna(row["緯度"]) and pd.notna(row["經度"]):
            popup_text = f"<b>{row['名稱']}</b><br>{row['介紹']}"
            folium.Marker(
                [float(row["緯度"]), float(row["經度"])],
                popup=folium.Popup(popup_text, max_width=250),
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
    st_folium(m, width="100%", height=600)

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        st.dataframe(filtered_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
    else:
        st.write("目前無資料。")
