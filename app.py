import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from streamlit_gsheets import GSheetsConnection

# --- 页面配置 ---
st.set_page_config(page_title="云端投资追踪器 (GSheets)", layout="wide", page_icon="📈")

# --- 数据库操作 (Google Sheets) ---

# 定义表头结构
COLUMNS = [
    "id", "symbol", "buy_price", "sell_price", "quantity", 
    "open_date", "close_date", "pnl", "pnl_percent", "status", "notes"
]

@st.cache_data(ttl=None)
def get_data_cached():
    """带缓存的读取函数"""
    conn = st.connection("gsheets", type=GSheetsConnection)
    # 这里不需要 ttl=0 了，因为外层有 cache_data 控制
    df = conn.read(worksheet="Sheet1")
    
    # 如果是空表，初始化列名
    if df.empty or len(df.columns) < len(COLUMNS):
        df = pd.DataFrame(columns=COLUMNS)
        # 初始化一个空表写入，防止后续报错
        conn.update(worksheet="Sheet1", data=df)
        return df
    
    # 确保列名正确（防止读取脏数据）
    # 有时候读取会多出空列，这里只取我们需要的列
    existing_cols = [c for c in COLUMNS if c in df.columns]
    df = df[existing_cols]
    
    # 补充缺失的列
    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None
            
    # 强制转换数据类型
    df['id'] = pd.to_numeric(df['id'], errors='coerce').fillna(0).astype(int)
    df['buy_price'] = pd.to_numeric(df['buy_price'], errors='coerce').fillna(0.0)
    df['sell_price'] = pd.to_numeric(df['sell_price'], errors='coerce').fillna(0.0)
    df['quantity'] = pd.to_numeric(df['quantity'], errors='coerce').fillna(0).astype(int)
    df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce').fillna(0.0)
    
    # 日期处理
    df['open_date'] = pd.to_datetime(df['open_date'], errors='coerce')
    df['close_date'] = pd.to_datetime(df['close_date'], errors='coerce')
    
    return df

def get_data():
    return get_data_cached()
    
def save_data(df):
    """将 DataFrame 写回 Google Sheets"""
    conn = st.connection("gsheets", type=GSheetsConnection)
    
    # 复制一份数据进行处理，以免影响原数据
    save_df = df.copy()
    
    # --- 修复核心：强制转换为 datetime 类型 ---
    # errors='coerce' 会把无法转换的数据（如空字符串、乱码）变成 NaT (时间格式的空值)
    save_df['open_date'] = pd.to_datetime(save_df['open_date'], errors='coerce')
    save_df['close_date'] = pd.to_datetime(save_df['close_date'], errors='coerce')

    # --- 现在可以安全使用 .dt 了 ---
    save_df['open_date'] = save_df['open_date'].dt.strftime('%Y-%m-%d')
    save_df['close_date'] = save_df['close_date'].dt.strftime('%Y-%m-%d')
    
    # 把 NaT 和 NaN 替换成空字符串，保持 Google Sheets 干净
    save_df = save_df.fillna("")
    
    conn.update(worksheet="Sheet1", data=save_df)

def add_buy_position(symbol, buy_price, quantity, open_date, notes):
    """开仓（买入）- 追加行"""
    df = get_data()
    
    # 自动生成 ID (取当前最大ID + 1)
    new_id = 1
    if not df.empty and 'id' in df.columns:
        if df['id'].max() > 0:
            new_id = int(df['id'].max()) + 1
            
    new_row = pd.DataFrame([{
        "id": new_id,
        "symbol": symbol.upper(),
        "buy_price": buy_price,
        "sell_price": 0.0,
        "quantity": quantity,
        "open_date": pd.to_datetime(open_date),
        "close_date": None,
        "pnl": 0.0,
        "pnl_percent": 0.0,
        "status": "OPEN",
        "notes": notes
    }])
    
    # 追加并保存
    updated_df = pd.concat([df, new_row], ignore_index=True)
    save_data(updated_df)

def close_position(trade_id, sell_price, close_date, notes):
    """平仓（卖出）- 更新行"""
    df = get_data()
    
    # 找到对应的行索引
    mask = df['id'] == trade_id
    
    if mask.any():
        idx = df[mask].index[0]
        
        # 获取原有信息
        buy_price = df.at[idx, 'buy_price']
        quantity = df.at[idx, 'quantity']
        old_notes = df.at[idx, 'notes']
        
        # 计算盈亏
        cost = buy_price * quantity
        revenue = sell_price * quantity
        pnl = revenue - cost
        pnl_percent = (pnl / cost) * 100 if cost != 0 else 0
        
        new_notes = (str(old_notes) + f" | 卖出备注: {notes}") if old_notes else notes
        
        # 更新 DataFrame
        df.at[idx, 'sell_price'] = sell_price
        df.at[idx, 'close_date'] = pd.to_datetime(close_date)
        df.at[idx, 'pnl'] = pnl
        df.at[idx, 'pnl_percent'] = pnl_percent
        df.at[idx, 'status'] = 'CLOSED'
        df.at[idx, 'notes'] = new_notes
        
        save_data(df)

def delete_trade(trade_id):
    """删除记录"""
    df = get_data()
    # 过滤掉要删除的 ID
    df = df[df['id'] != trade_id]
    save_data(df)

def get_open_positions():
    df = get_data()
    if df.empty: return df
    return df[df['status'] == 'OPEN']

def get_closed_trades():
    df = get_data()
    if df.empty: return df
    df = df[df['status'] == 'CLOSED']
    # 确保日期列是 datetime 对象以便排序
    df['close_date'] = pd.to_datetime(df['close_date'])
    return df.sort_values(by='close_date', ascending=False)

# --- 侧边栏：核心操作区 ---
st.sidebar.header("📝 交易操作")

# 1. 选择操作模式
action_type = st.sidebar.radio("选择操作类型", ["🔵 新建买入 (建仓)", "🔴 平仓卖出 (结算)"])

with st.sidebar.form("trade_form", clear_on_submit=True):
    
    if "买入" in action_type:
        st.subheader("建仓信息")
        symbol = st.text_input("股票代码 (如 AAPL)", max_chars=10)
        col1, col2 = st.columns(2)
        with col1:
            price = st.number_input("买入价格 ($)", min_value=0.0, format="%.2f")
        with col2:
            quantity = st.number_input("买入数量", min_value=1, step=1)
        
        date_val = st.date_input("买入日期", datetime.today())
        notes = st.text_area("策略笔记")
        
        submitted = st.form_submit_button("💾 确认买入")
        
        if submitted:
            if symbol and price > 0 and quantity > 0:
                with st.spinner("正在写入 Google Sheets..."):
                    add_buy_position(symbol, price, quantity, date_val, notes)
                st.sidebar.success(f"已建立 {symbol} 持仓！")
            else:
                st.sidebar.error("请填写完整信息")

    else:
        st.subheader("平仓操作")
        open_positions = get_open_positions()
        
        if open_positions.empty:
            st.warning("当前没有持仓可卖。请先买入。")
            submitted = st.form_submit_button("刷新状态")
        else:
            options = {f"{row['symbol']} (成本: {row['buy_price']}, 股数: {row['quantity']}) - ID:{row['id']}": row['id'] 
                       for index, row in open_positions.iterrows()}
            
            selected_label = st.selectbox("选择要卖出的持仓", list(options.keys()))
            selected_id = options[selected_label]
            
            col1, col2 = st.columns(2)
            with col1:
                price = st.number_input("卖出价格 ($)", min_value=0.0, format="%.2f")
            with col2:
                st.caption("目前支持全仓卖出")
            
            date_val = st.date_input("卖出日期", datetime.today())
            notes = st.text_input("卖出备注")
            
            submitted = st.form_submit_button("💰 确认卖出")
            
            if submitted:
                if selected_id and price > 0:
                    with st.spinner("正在更新 Google Sheets..."):
                        close_position(selected_id, price, date_val, notes)
                    st.sidebar.success("交易已平仓！")
                    st.rerun()

# --- 主页面 ---
st.title("📈 投资仓位管理 (Google Sheets版)")

# 1. 顶部：当前持仓
st.subheader("💼 当前持仓 (Holding)")
open_df = get_open_positions()

if open_df.empty:
    st.info("目前空仓，请在左侧添加买入记录。")
else:
    open_df['Cost Basis'] = open_df['buy_price'] * open_df['quantity']
   # 格式化显示日期
    display_open = open_df.copy()
    # 强制转为 datetime 后再取 date，防止报错    
    display_open['open_date'] = pd.to_datetime(display_open['open_date'], errors='coerce').dt.date
    st.dataframe(display_open[['symbol', 'buy_price', 'quantity', 'open_date', 'notes']], use_container_width=True)
    st.caption(f"当前持仓总成本: ${open_df['Cost Basis'].sum():,.2f}")

st.markdown("---")

# 2. 底部：历史盈亏
st.subheader("📊 历史盈亏分析 (Closed)")
closed_df = get_closed_trades()

if not closed_df.empty:
    total_invested = (closed_df['buy_price'] * closed_df['quantity']).sum()
    total_pnl = closed_df['pnl'].sum()
    win_rate = len(closed_df[closed_df['pnl'] > 0]) / len(closed_df) * 100 if len(closed_df) > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("已落袋总盈亏", f"${total_pnl:,.2f}", delta_color="normal")
    c2.metric("交易胜率", f"{win_rate:.1f}%")
    c3.metric("总交易数", len(closed_df))

    col_chart1, col_chart2 = st.columns(2)
    
    with col_chart1:
        closed_df_sorted = closed_df.sort_values(by='close_date')
        closed_df_sorted['cumulative_pnl'] = closed_df_sorted['pnl'].cumsum()
        fig_line = px.line(closed_df_sorted, x='close_date', y='cumulative_pnl', title="资金曲线", markers=True)
        st.plotly_chart(fig_line, use_container_width=True)
    
    with col_chart2:
        closed_df['color'] = closed_df['pnl'].apply(lambda x: '盈利' if x >= 0 else '亏损')
        fig_bar = px.bar(closed_df, x='symbol', y='pnl', color='color', 
                         color_discrete_map={'盈利': '#00CC96', '亏损': '#EF553B'},
                         title="个股盈亏分布")
        st.plotly_chart(fig_bar, use_container_width=True)

    with st.expander("查看详细历史交易记录"):
        display_cols = ['symbol', 'open_date', 'close_date', 'buy_price', 'sell_price', 'quantity', 'pnl', 'pnl_percent', 'notes']
        display_closed = closed_df[display_cols].copy()
        
        # --- 修复点：强制转换后再取 .dt.date ---
        display_closed['open_date'] = pd.to_datetime(display_closed['open_date'], errors='coerce').dt.date
        display_closed['close_date'] = pd.to_datetime(display_closed['close_date'], errors='coerce').dt.date
        
        st.dataframe(display_closed, use_container_width=True)
        csv = display_closed.to_csv(index=False).encode('utf-8')
        st.download_button("📥 导出历史记录 CSV", csv, "closed_trades.csv", "text/csv")
        
        st.dataframe(display_closed, use_container_width=True)
        csv = display_closed.to_csv(index=False).encode('utf-8')
        st.download_button("📥 导出历史记录 CSV", csv, "closed_trades.csv", "text/csv")
else:
    st.info("暂无卖出记录。")

# --- 放在 app.py 最底部 ---
st.markdown("---")
with st.expander("🗑️ 数据管理：删除记录"):
    st.warning("⚠️ 警告：删除将同步到 Google Sheets，不可恢复！")
    
    df_all = get_data()
    if df_all.empty:
        st.info("无数据。")
    else:
        # 按 ID 倒序排列，方便删最新的
        df_all = df_all.sort_values(by='id', ascending=False)
        delete_options = {
            f"[{row['status']}] {row['symbol']} ({pd.to_datetime(row['open_date']).date()}) - ID:{row['id']}": row['id']
            for index, row in df_all.iterrows()
        }

        selected_label = st.selectbox("选择要删除的记录", list(delete_options.keys()))
        target_id = delete_options[selected_label]

        if st.button("❌ 确认删除选中记录"):
            with st.spinner("正在删除..."):
                delete_trade(target_id)
            st.success(f"ID {target_id} 已删除！")
            st.rerun()
