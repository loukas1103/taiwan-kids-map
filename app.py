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

# --- 1. 資料匯入與強效標準化邏輯 ---
@st.cache_data(ttl=3600)
def load_all_data():
    all_pois = []
    
    # 標準縣市清單 (用於最後的校準)
    STANDARD_CITIES = [
        "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
        "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
        "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
        "臺東縣", "澎湖縣", "金門縣", "連江縣"
    ]

    # --- 方法 A: 政府 XML 資料 ---
    try:
        # 觀光署資料來源
        gov_url = "https://media.taiwan.net.tw/XMLReleaseALL_public/scenic_spot_C_f.xml"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(gov_url, headers=headers, timeout=20, verify=False)
        response.encoding = 'utf-8'
        root = ET.fromstring(response.content)
        
        for info in root.findall(".//Info"):
            try:
                name = info.find('Name').text.strip() if info.find('Name') is not None else "未知景點"
                
                # 優先抓取 Region 欄位，這通常是縣市名稱
                region = info.find('Region').text.strip() if info.find('Region') is not None else ""
                
                # 如果 Region 空缺，則解析地址 Add 欄位
                if not region:
                    raw_add = info.find('Add').text.strip() if info.find('Add') is not None else ""
                    # 統一將「台」轉為「臺」
                    normalized_add = raw_add.replace("台", "臺")
                    for c in STANDARD_CITIES:
                        if c in normalized_add:
                            region = c
                            break
                
                # 再次校正 region 字串
                region = region.replace("台", "臺")
                if "臺北市" in region or region == "臺北": region = "臺北市"
                
                px = info.find('Px').text
                py = info.find('Py').text
                
                if px and py:
                    all_pois.append({
                        "名稱": name,
                        "縣市": region, 
                        "介紹": (info.find('Description').text[:100] + "...") if info.find('Description') is not None else "暫無介紹",
                        "緯度": float(py),
                        "經度": float(px)
                    })
            except:
                continue
    except Exception as e:
        st.error(f"政府資料讀取失敗: {e}")

    # --- 方法 B: Google 表單 CSV ---
    # 請確保此 URL 是「發布到網路」並選擇「CSV」格式的連結
    SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSTCgMNKX0_D5fre8tFYOE32i_9ikAwx7yOlz5nl0fMbhPVfIQHU32-l2y_jUe1mAInQhlB0ia_A6hy/pub?output=csv"
    try:
        sheet_df = pd.read_csv(SHEET_CSV_URL)
        sheet_df.columns = sheet_df.columns.str.strip()
        
        # 欄位對照表：將表單可能的名稱映射到程式統一名稱
        column_mapping = {
            '景點名稱': '名稱',
            '縣市': '縣市',
            '地址': '縣市',
            '介紹': '介紹',
            '緯度': '緯度',
            'Lat': '緯度',
            '經度': '經度',
            'Lng': '經度'
        }
        sheet_df = sheet_df.rename(columns=column_mapping)
        
        # 確保縣市欄位格式統一
        if '縣市' in sheet_df.columns:
            def clean_city(x):
                x = str(x).replace("台", "臺")
                for c in STANDARD_CITIES:
                    if c in x: return c
                return x
            sheet_df['縣市'] = sheet_df['縣市'].apply(clean_city)
        
        # 僅選取需要的欄位並併入
        valid_cols = [c for c in ["名稱", "縣市", "介紹", "緯度", "經度"] if c in sheet_df.columns]
        all_pois.extend(sheet_df[valid_cols].to_dict('records'))
    except Exception as e:
        st.warning(f"表單讀取失敗: {e}")

    # --- 資料清洗與轉換 ---
    df = pd.DataFrame(all_pois)
    if not df.empty:
        df['緯度'] = pd.to_numeric(df['緯度'], errors='coerce')
        df['經度'] = pd.to_numeric(df['經度'], errors='coerce')
        df = df.dropna(subset=['緯度', '經度'])
        df['縣市'] = df['縣市'].astype(str).str.strip()
    
    return df

# 載入資料
poi_df = load_all_data()

# --- 2. 搜尋介面 ---
st.sidebar.header("🔍 搜尋條件")
target_address = st.sidebar.text_input("1. 輸入您的位置", "台北車站")

TAIWAN_CITIES = [
    "臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", 
    "基隆市", "新竹縣", "新竹市", "苗栗縣", "彰化縣", "南投縣", 
    "雲林縣", "嘉義縣", "嘉義市", "屏東縣", "宜蘭縣", "花蓮縣", 
    "臺東縣", "澎湖縣", "金門縣", "連江縣"
]
city_filter = st.sidebar.selectbox("2. 選擇縣市", ["全部縣市"] + TAIWAN_CITIES)
keyword = st.sidebar.text_input("3. 景點關鍵字")

# 定位我的位置
geolocator = Nominatim(user_agent="taiwan_kids_map_v5")
try:
    loc = geolocator.geocode(target_address)
    if loc:
        center_coords = (loc.latitude, loc.longitude)
    else:
        # 若找不到地址，預設台北車站
        center_coords = (25.0478, 121.5170)
except:
    center_coords = (25.0478, 121.5170)

# 篩選邏輯
filtered_df = poi_df.copy()

if city_filter != "全部縣市":
    filtered_df = filtered_df[filtered_df["縣市"] == city_filter]

if keyword:
    search_key = keyword.replace("台", "臺")
    filtered_df = filtered_df[filtered_df["名稱"].str.contains(search_key, na=False)]

# 計算距離
if not filtered_df.empty:
    filtered_df["距離(km)"] = filtered_df.apply(
        lambda r: round(geodesic(center_coords, (r["緯度"], r["經度"])).km, 2), axis=1
    )
    filtered_df = filtered_df.sort_values("距離(km)")

# --- 3. 顯示結果 ---
st.title("🎡 全台親子旅遊自動化查詢站")
st.markdown(f"目前搜尋中心：**{target_address}** ({center_coords[0]:.4f}, {center_coords[1]:.4f})")

col_map, col_info = st.columns([2, 1])

with col_map:
    st.subheader("🗺️ 景點分佈地圖")
    m = folium.Map(location=center_coords, zoom_start=13)
    
    # 標記中心點
    folium.Marker(
        center_coords, 
        popup="我的位置", 
        icon=folium.Icon(color="red", icon="home")
    ).add_to(m)
    
    # 顯示前 100 筆景點（避免地圖過於擁擠）
    for _, row in filtered_df.head(100).iterrows():
        popup_html = f"""
        <div style='width:200px'>
            <h4>{row['名稱']}</h4>
            <p><b>縣市：</b>{row['縣市']}</p>
            <p><b>距離：</b>{row['距離(km)']} km</p>
            <p style='font-size: 0.9em; color: gray;'>{row.get('介紹', '無介紹')}</p>
        </div>
        """
        folium.Marker(
            [row["緯度"], row["經度"]],
            popup=folium.Popup(popup_html, max_width=250),
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)
    
    st_folium(m, width="100%", height=600, key="main_map")

with col_info:
    st.subheader("📋 景點列表")
    if not filtered_df.empty:
        # 顯示 Dataframe 並美化
        display_df = filtered_df[["名稱", "縣市", "距離(km)"]].copy()
        st.dataframe(
            display_df, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "距離(km)": st.column_config.NumberColumn(format="%.2f km")
            }
        )
    else:
        st.info("符合條件的景點目前不在資料庫中。")
