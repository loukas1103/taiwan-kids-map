import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
from geopy.geocoders import Nominatim
import time
import os

def sync_from_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # --- 修改重點：改從 st.secrets 讀取 ---
        # 這裡會讀取你在 Streamlit 網頁後台設定的 [gcp_service_account] 區塊
        secret_dict = dict(st.secrets["gcp_service_account"])
        
        # 處理 private_key 中的換行符號問題（有時複製貼上會跑掉）
        if "private_key" in secret_dict:
            secret_dict["private_key"] = secret_dict["private_key"].replace("\\n", "\n")
            
        creds = ServiceAccountCredentials.from_json_keyfile_dict(secret_dict, scope)
        client = gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 讀取雲端 Secrets 失敗: {e}")
        return

    # 試算表 ID (請確認已共用給 Secrets 裡的 client_email)
    spreadsheet_id = "將你的試算表ID貼在這裡" 
    
    try:
        sh = client.open_by_key(spreadsheet_id)
        sheet = sh.get_worksheet(0)
        sheet_data = sheet.get_all_records()
        new_df = pd.DataFrame(sheet_data)
    except Exception as e:
        print(f"❌ 開啟試算表失敗: {e}")
        return

    if new_df.empty:
        print("⚠️ 雲端表單目前沒有新資料。")
        return

    # 讀取本地 CSV
    csv_file = 'locations.csv'
    if os.path.exists(csv_file):
        old_df = pd.read_csv(csv_file)
    else:
        old_df = pd.DataFrame(columns=['名稱', '城市', '類型', '分齡', 'lat', 'lon', '介紹'])

    # 合併與去重
    combined_df = pd.concat([old_df, new_df]).drop_duplicates(subset=['名稱'], keep='first')

    # 自動補齊座標 (維持原邏輯)
    geolocator = Nominatim(user_agent="taiwan_kids_sync_cloud")
    
    for index, row in combined_df.iterrows():
        if pd.isna(row.get('lat')) or row.get('lat') == 0 or row.get('lat') == "":
            addr = row.get('詳細地址') or row.get('地址') or f"{row['城市']} {row['名稱']}"
            try:
                location = geolocator.geocode(addr)
                if location:
                    combined_df.at[index, 'lat'] = location.latitude
                    combined_df.at[index, 'lon'] = location.longitude
                    time.sleep(1.2)
            except:
                continue

    # 存回 CSV
    combined_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print("🚀 同步與座標補齊完成！")

if __name__ == "__main__":
    sync_from_google_sheets()
