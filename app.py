import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import os

# --- 網頁基礎設定 ---
st.set_page_config(page_title="親子旅遊地圖", layout="wide")

# --- 1. 引入同步功能 ---
try:
    from sync_data import sync_from_google_sheets
except ImportError:
    st.error("找不到 sync_data.py，請確認檔案已上傳至 GitHub。")

# --- 2. 側邊欄：管理功能 ---
st.sidebar.title("🛠️ 管理選單")

if st.sidebar.button("🔄 同步最新雲端資料"):
    with st.spinner("正在連線 Google 試算表並計算座標..."):
        try:
            sync_from_google_sheets()
            # 同步後強制清除快取，否則地圖會顯示舊資料
            st.cache_data.clear()
            st.sidebar.success("同步成功！")
            st.rerun()
        except Exception as e:
            st.sidebar.error(f"同步失敗: {e}")

# --- 3. 資料讀取與清洗 (防止 ValueError) ---
@st.cache_data
def load_data():
    csv_path = 'locations.csv'
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    
    # 讀取檔案
    df = pd.read_csv(csv_path)
    
    # 【關鍵防錯】
    # 1. 剔除座標欄位有空值 (NaN) 的列
    df = df.dropna(subset=['lat', 'lon'])
    
    # 2. 強制轉換座標為數字，失敗的會變成 NaN 然後被刪除
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
    df = df.dropna(subset=['lat', 'lon'])
    
    # 3. 剔除座標為 0 的無效資料
    df = df[(df['lat'] != 0) & (df['lon'] != 0)]
    
    return df

# 載入清洗後的資料
df = load_data()

# --- 4. 主畫面顯示 ---
st.title("📍 台灣親子旅遊地圖")
st.write("這是為家長設計的假日出遊參考工具，資料同步自 Google 表單。")

if df.empty:
    st.info("目前地圖上沒有資料，請點擊左側「同步」按鈕來獲取資料。")
else:
    # 顯示目前景點統計
    col1, col2, col3 = st.columns(3)
    col1.metric("景點總數", len(df))
    
    # 側邊欄篩選 (選擇性)
    if '類型' in df.columns:
        selected_type = st.sidebar.multiselect("篩選類型", options=df['類型'].unique(), default=df['類型'].unique())
        df = df[df['類型'].isin(selected_type)]

    # 建立地圖
    # 設定中心點在台灣 [23.6, 121.0]
    m = folium.Map(location=[23.6, 121.0], zoom_start=7, control_scale=True)

    # 繪製圖釘
    for index, row in df.iterrows():
        # 建立彈出視窗內容
        popup_html = f"""
        <div style='font-family: sans-serif; width: 200px;'>
            <h4>{row['名稱']}</h4>
            <p><b>類型：</b>{row.get('類型', '未分類')}</p>
            <p><b>介紹：</b>{row.get('介紹', '暫無說明')}</p>
        </div>
        """
        
        folium.Marker(
            location=[row['lat'], row['lon']],
            popup=folium.Popup(popup_html, max_width=250),
            tooltip=row['名稱'],
            icon=folium.Icon(color='blue', icon='info-sign')
        ).add_to(m)

    # 呈現地圖
    st_folium(m, width="100%", height=600)

# --- 底部宣告 ---
st.markdown("---")
st.caption("資料來源：Google Sheets | 開發工具：Streamlit & Folium")
