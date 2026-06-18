# ══════════════════════════════════════════════
# TAB 3 — ANÁLISIS HISTÓRICO POR EA
# ══════════════════════════════════════════════
with tab3:
    st.subheader("📊 Análisis Cuantitativo por EA — Reporte MT5 (Deals)")
    st.markdown("""
    Exporta desde MT5 $\rightarrow$ Historial $\rightarrow$ Reporte $\rightarrow$ Open XML (Excel). 
    La app detectará automáticamente las posiciones vinculadas y recuperará el nombre del EA original aunque haya cerrado por SL/TP.
    """)
    
    # Reutilizamos el uploader del reporte real si ya se subió en la Tab 1, o creamos uno nuevo
    archivo_tab3 = archivo_real if archivo_real else st.file_uploader("Subir reporte MT5 (.csv, .xlsx, .html)", key="uploader_tab3")

    if archivo_tab3:
        try:
            archivo_tab3.seek(0)
            df_raw = leer_archivo_inteligente(archivo_tab3)
            
            # Aplicamos la magia del algoritmo de mapeo de posiciones
            df_procesado = mapear_comentarios_mt5(df_raw)
            
            # Detectar columnas universales para cálculos monetarios
            col_fecha, col_profit = encontrar_columnas_universal(df_procesado)
            
            # Normalizar nombres de columnas internas para que 'calcular_metricas_portfolio' funcione
            df_procesado['Beneficio'] = pd.to_numeric(
                df_procesado[col_profit].astype(str).str.replace(r'[^\d\.\-]', '', regex=True), 
                errors='coerce'
            ).fillna(0)
            
            # Si no hay columna equity acumulada, la calculamos dinámicamente para el drawdown
            if 'equity' not in df_procesado.columns:
                df_procesado = df_procesado.sort_values(col_fecha)
                df_procesado['Equity'] = st.session_state['capital_inicial'] + df_procesado['Beneficio'].cumsum()

            # --- RENDERIZADO DE MÉTRICAS GLOBALES ---
            metricas_globales = calcular_metricas_portfolio(df_procesado)
            
            st.markdown("### 📈 Performance Global del Portfolio")
            g1, g2, g3, g4, g5 = st.columns(5)
            g1.metric("Net Profit", f"${metricas_globales.get('net_profit', 0):,.2f}")
            g2.metric("Profit Factor", f"{metricas_globales.get('profit_factor', 0)}")
            g3.metric("Win Rate", f"{metricas_globales.get('win_rate', 0)}%")
            g4.metric("Expectancy", f"${metricas_globales.get('expectancy', 0)}")
            g5.metric("Total Trades", metricas_globales.get('total_trades', 0))
            
            st.write("---")
            st.markdown("### 🏆 Ranking de EAs por Performance Real")

            # --- AGRUPACIÓN POR EA (Usando nuestra columna 'ea_limpio') ---
            ranking_data = []
            for name, group in df_procesado.groupby('ea_limpio'):
                if group['Beneficio'].abs().sum() == 0: 
                    continue # Evitamos meter filas vacías de transacciones sin balance
                    
                m = calcular_metricas_portfolio(group)
                
                # Semáforo de estado basado en Profit Factor
                pf = m.get('profit_factor', 0)
                status = "🔴" if pf < 1.1 else "🟡" if pf < 1.4 else "🟢"
                
                ranking_data.append({
                    "Estado": status,
                    "EA / Estrategia": name,
                    "Trades": m.get('total_trades', 0),
                    "Net Profit": round(m.get('net_profit', 0), 2),
                    "PF": pf,
                    "WR%": f"{m.get('win_rate', 0)}%",
                    "Avg Win": f"${m.get('avg_win', 0)}",
                    "Avg Loss": f"${m.get('avg_loss', 0)}",
                    "Expectancy": f"${m.get('expectancy', 0)}",
                    "Max DD": f"{m.get('max_dd_pct', 0)}%"
                })
            
            df_ranking = pd.DataFrame(ranking_data)
            if not df_ranking.empty:
                df_ranking = df_ranking.sort_values(by="Net Profit", ascending=False).reset_index(drop=True)
                st.dataframe(df_ranking, use_container_width=True)
            else:
                st.warning("No se pudieron extraer métricas individuales por EA. Verifica la estructura del archivo.")

        except Exception as e:
            st.error(f"❌ Error al procesar el ranking de la Tab 3: {e}")
    else:
        st.info("💡 Por favor, sube un reporte detallado en formato Excel/HTML de MT5 para cruzar las posiciones y limpiar los cierres.")
