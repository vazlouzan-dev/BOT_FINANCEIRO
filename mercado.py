import yfinance as yf

print("A contactar os mercados financeiros...")

# Vamos buscar os dados do fundo que segue o S&P 500 (o código na bolsa é SPY)
indice = yf.Ticker("SPY")

# Pedimos o histórico de preços de hoje ("1d" = 1 day)
dados_hoje = indice.history(period="1d")

# Vamos extrair o preço mais recente
preco_atual = dados_hoje['Close'].iloc[-1]

print(f"O preço mais recente do S&P 500 (SPY) é: {preco_atual:.2f} dólares")