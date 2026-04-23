import streamlit as st
import pandas as pd
import folium
import requests
import xml.etree.ElementTree as ET
import urllib3
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# 消除 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 設定頁面配置
st.set_page_config(layout="wide", page_title="全台親子旅遊自動化查詢站")

# --- 1. 定義搜尋介面 (統一選單為「臺」) ---
TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]

st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")
# 選單顯示「臺北市」，但我們會讓它同時能搜到「台北市」的資料
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字 (台/臺通用)")
search_button = st.sidebar.button("開始搜尋")

# --- 2. 隨條件匯入資料的邏輯 ---
@st.cache_data(ttl=3600)
def get_filtered_data(city_q, keyword_q):
    all_pois = []
    # 將使用者的關鍵字也進行「台/臺」同步
    search_keyword = keyword_q.replace("台", "臺") if keyword_q else ""
    
    # --- 方法 A: 政府 XML ---
    try:
        # 觀光署穩定版 XML 連結
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        response = requests.get(gov_url, timeout=15, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text if info.find('Name') is not None else ""
                add = info.find('Add').text if info.find('Add') is not None else ""
                
                # 【核心技術】將資料中的「台」統一轉為「臺」進行邏輯比對
                norm_add = add.replace("台", "臺")
                norm_name = name.replace("台", "臺")
                
                # 篩選條件：只要地址包含選定的縣市名 (如地址含「台北」或「臺北」都會中)
                is_city_match = (city_q == "全部縣市") or (city_q in norm_add)
                
                # 篩選條件：關鍵字匹配
                is_keyword_match = not search_keyword or (search_keyword in norm_name) or (search_keyword in norm_add)
                
                if is_city_match and is_keyword_match:
                    px = info.find('Px').text
                    py = info.find('Py').text
                    if px and py:
                        all_pois.append({
                            "名稱": name,
                            "縣市": city_q if city_q != "全部縣市" else norm_add[:3],
                            "介紹": (info.find('Description').text[:50] + "...") if info.find('Description') is not None else "暫無介紹",
                            "緯度": float(py),
                            "經度": float(px)
                        })
            except:
                continue
    except Exception as e:
        st.error(f"政府資料連線失敗: {e}")

    # --- 方法 B: Google 表單 CSV ---
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        sheet_df.columns = sheet_df.columns.str.strip()
        
        # CSV 資料標準化
        if '縣市' in sheet_df.columns:
            sheet_df['縣市_norm'] = sheet_df['縣市'].astype(str).str.replace("台", "臺")
        
        # 進行篩選
        if city_q != "全部縣市":
            sheet_df = sheet_df[sheet_df['縣市_norm'] == city_q]
        if search_keyword:
            sheet_df = sheet_df[sheet_df['名稱'].str.replace("台", "臺").str.contains(search_keyword, na=False)]
            
        all_pois.extend(sheet_df.to_dict('records'))
    except:
        pass

    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
    return df

# --- 3. 執行搜尋與地理定位 ---
if search_button:
    with st.spinner('正在同步「台/臺」北市景點資料...'):
        final_df = get_filtered_data(city_filter, keyword)

    # 地理定位中心
    geolocator = Nominatim(user_agent="taiwan_kids_v6")
    try:
        loc = geolocator.geocode(target_address)
        center_coords = (loc.latitude, loc.longitude) if loc else (25.0478, 121.5170)
    except:
        center_coords = (25.0478, 121.5170)

    # 計算距離與排序
    if not final_df.empty:
        final_df["距離(km)"] = final_df.apply(
            lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
        )
        final_df = final_df.sort_values("距離(km)")

    # --- 4. 畫面顯示 ---
    col_map, col_info = st.columns([2, 1])

    with col_map:
        st.subheader(f"🗺️ {city_filter} 地圖結果 (共 {len(final_df)} 筆)")
        # 建立地圖物件
        m = folium.Map(location=center_coords, zoom_start=13)
        folium.Marker(center_coords, popup="搜尋中心", icon=folium.Icon(color="red")).add_to(m)
        
        # 只顯示前 100 筆，避免瀏覽器卡死
        for _, row in final_df.head(100).iterrows():
            popup_html = f"<b>{row['名稱']}</b><br>{row.get('介紹', '')}"
            folium.Marker(
                [row["緯度"], row["經度"]],
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color="blue", icon="info-sign")
            ).add_to(m)
        
        # 強制更新地圖 Key
        st_folium(m, width="100%", height=600, key=f"map_{city_filter}")

    with col_info:
        st.subheader("📋 景點清單")
        if not final_df.empty:
            st.dataframe(final_df[["名稱", "縣市", "距離(km)"]], use_container_width=True, hide_index=True)
        else:
            st.warning("查無資料，請嘗試放寬關鍵字或檢查選單。")
else:
    # 初始頁面顯示
    st.info("👋 歡迎！請在左側選擇縣市（如：臺北市）並點擊「開始搜尋」，我們將自動為您合併『台』與『臺』的搜尋結果。")
    st.image("https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?auto=format&fit=crop&q=80&w=1000", caption="準備好出發了嗎？")
