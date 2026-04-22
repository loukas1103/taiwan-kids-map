import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import os

# 設定網頁標題
st.set_page_config(page_title="台灣親子景點地圖", layout="wide")

# --- 1. 同步功能 (引用外部 sync_data.py) ---
try:
    from sync_data import sync_from_google_sheets
except ImportError:
    st.error("找不到 sync_data.py 檔案，請確認檔案已上傳至 GitHub。")

# --- 2. 側邊欄：同步按鈕 ---
st.sidebar.title("管理工具")
if st.sidebar.button("🔄 同步最新雲端資料"):
    with st.spinner("正在連線 Google 試算表並更新座標..."):
        try:
            sync_from_google_sheets()
            st.cache_data.clear() # 清除快取，確保讀到新 CSV
            st.success("同步成功！")
            st.rerun()
        except Exception as e:
            st.error(f"同步失敗: {e}")

# --- 3. 讀取並過濾資料 ---
@st.cache_data
def load_and_clean_data():
    if not os.path.exists('locations.csv'):
        return pd.DataFrame()
    
    # 讀取 CSV
    df = pd.read_csv('locations.csv')
    
    # 【關鍵除錯區】過濾掉會導致 ValueError 的資料
    # 1. 刪除 lat 或 lon 是空的列
    df = df.dropna(subset=['lat', 'lon'])
    
    # 2. 強制轉換為數字，若轉換失敗（例如填入文字）會變成 NaN
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
    
    # 3. 再次刪除轉換失敗後的空列
    df = df.dropna(subset=['lat', 'lon'])
    
    # 4. 剔除座標為 0 的無效點
    df = df[(df['lat'] != 0) & (df['lon'] != 0)]
    
    return df

df = load_and_clean_data()

# --- 4. 地圖呈現 ---
st.title("📍 台灣親子旅遊地圖")

if df.empty:
    st.warning("目前地圖上沒有有效的景點資料。請點擊左側按鈕同步，或檢查 locations.csv。")
else:
    st.write(f"目前顯示景點數量：{len(df)}")
    
    # 建立地圖中心點 (以台灣中心為準)
    m = folium.Map(location=[23.6, 121.0], zoom_start=7)

    # 繪製圖釘
    for index, row in df.iterrows():
        try:
            folium.Marker(
                location=[row['lat'], row['lon']],
                popup=f"<b>{row['名稱']}</b><br>{row.get('介紹', '')}",
                tooltip=row['名稱'],
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(m)
        except Exception as e:
            continue # 萬一還有奇葩資料，跳過該點而不讓整張地圖當機

    # 顯示地圖
    st_folium(m, width=1000, height=600)
