"""
Descrição:
Este arquivo implementa um servidor web utilizando Flask, projetado para:

1: receber a URL de uma NFC-e, extrair seus dados e armazená-los em um banco de dados
Supabase.

    O processo consiste em:
    1.  Receber uma requisição POST no endpoint '/nota' contendo a URL da nota fiscal.
    2.  Utilizar o Selenium para carregar dinamicamente a página web da URL,
        garantindo que todo o conteúdo gerado por JavaScript seja renderizado.
    3.  Após o carregamento, o conteúdo HTML completo da página é extraído.
    4.  A biblioteca BeautifulSoup é usada para analisar (parse) o HTML e extrair
        informações detalhadas da nota, como dados do estabelecimento (nome, CNPJ,
        endereço), data da compra, valores totais (valor pago, descontos) e uma
        lista completa de todos os itens adquiridos.
    5.  Os dados extraídos são então inseridos em duas tabelas no banco de dados
        Supabase:
        - 'compra': armazena as informações gerais da nota fiscal.
        - 'produto': armazena cada item individual da compra, associado à sua
        respectiva nota pela chave de acesso.

2: retornar feedbacks das ultimas tentativas de insercao de novas notas 

Como executar:
Certifique-se de que todas as dependências estão instaladas e execute o
servidor com o seguinte comando no terminal:
`flask --app webserver.py run`
"""
import traceback

from flask import Flask, request, jsonify

from supabase import create_client, Client

from bs4 import BeautifulSoup
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

supabase: Client = create_client("https://pazlmdortizdhtapvggl.supabase.co", "sb_publishable_wYkgPWl_6L-nIP4BXpcsyw_Rze-1iwb")

app = Flask(__name__)

feedbacks = []

@app.route('/')
def hello_world():
    try:
        return 'Hello from Flask!'
    except Exception as e:
        print(f"Um erro ocorreu: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
@app.route('/feedback')
def get_feedback():
    if len(feedbacks) > 0:
        return feedbacks.pop()
    else:
        return {"code": 0, "message": "Sem novos feedbacks"}


@app.route('/nota', methods=['POST'])
def nota():
    try:
        content = request.form['content']
        if "https://sat.sef.sc.gov.br/tax.NET/Sat.DFe.NFCe.Web/Consultas/NFCe_Detalhes.aspx" in content:
            nfce = extrair_dados_nfce(extrair_HTML(content))
            inserir_dados_nfce_bd(nfce)
            feedbacks.append({"code": 200, "message": "Nova nota inserida com sucesso."})
            return jsonify(nfce), 200
        else: 
            feedbacks.append({"code": 400, "message": "Conteudo nao bate com link esperado."})
            return "Erro: Conteudo nao bate com link esperado", 400
    except ValueError as ve:
        print(f"Um erro ocorreu: {ve}")
        traceback.print_exc()
        return jsonify({"erro": str(ve)}), 409
    except Exception as e:
        print(f"Um erro ocorreu: {e}")
        traceback.print_exc()
        feedbacks.append({"code": 400, "message": f"Um erro ocorreu: {e}"})
        return jsonify({"error": str(e)}), 400

def extrair_HTML(url):
    """
    Extrai conteudo HTML a partir de url utilizando selenium para garantir
    que a pagina carregou totalmente

    Args:
        url (str): a url da pagina web.

    Return:
        str: O conteudo HTML da pagina.
    """

    # Configura as opções do Chrome
    options = webdriver.ChromeOptions()
    options.add_argument('--headless') 
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--log-level=3')
    options.add_experimental_option('excludeSwitches', ['enable-logging'])


    # Instala e configura o ChromeDriver automaticamente
    service = ChromeService(ChromeDriverManager().install())

    driver = None
    try:
        driver = webdriver.Chrome(service=service, options=options)
        
        # 1. Navegador carrega a URL
        driver.get(url)
        
        # 2. Espera explícita de até 20 segundos
        #    Aguarde até que a tabela de resultados com id='tabResult' esteja visível.
        WebDriverWait(driver, 20).until(
            EC.visibility_of_element_located((By.ID, "tabResult"))
        )
        
        # 3. Pega o código-fonte da página APÓS a execução do JavaScript
        html_completo = driver.page_source
        return html_completo
        
    finally:
        # Garante que o navegador seja fechado ao final
        if driver:
            driver.quit()

    # response = requests.get(url, timeout=20)
    # response.raise_for_status()  # Para verificar codigos de erro
    # return response.text

def extrair_dados_nfce(html_content):
    """
    Extrai informações de uma nota fiscal de consumidor eletronica (NFC-e)
    a partir de um conteúdo HTML.

    Args:
        html_content (str): O conteúdo HTML da pagina da NFC-e.

    Return:
        dict: Um dicionario contendo as informações extraidas.
    """
    soup = BeautifulSoup(html_content, 'lxml')

    # Dicionário para armazenar as informações
    nfce_data = {}

    # --- Extrair informações do comércio ---
    nfce_data['nome_comercio'] = soup.find('div', class_='txtTopo').get_text(strip=True)

    # Encontrar a div que contém o CNPJ
    cnpj_div = soup.find('div', string=lambda text: 'CNPJ:' in text)
    if cnpj_div:
        # Extrair o texto da div e remover "CNPJ:" e espaços em branco
        nfce_data['CNPJ'] = cnpj_div.get_text(strip=True).replace('CNPJ:', '').strip()

    # Encontrar a div que contém o endereço
    endereco_div = soup.find('div', class_='text', string=lambda text: 'CNPJ:' not in text)
    if endereco_div:
        # Normalizar o texto para remover quebras de linha e múltiplos espaços
        endereco_texto = ' '.join(endereco_div.get_text(strip=True).split())
        nfce_data['endereco'] = endereco_texto

    # --- Extrair a data da compra ---
    # Busca o div colapsível que contém as informações gerais

    collapsible_divs = soup.find_all('div', {'data-role': 'collapsible'})

    for div in collapsible_divs:
        h4 = div.find('h4')
        if h4 and 'Informações gerais da Nota' in h4.get_text():
            content_div = h4.find_next_sibling('div', class_='ui-collapsible-content')
            if content_div:
                li_emissao = content_div.find('li')
                if li_emissao:
                    texto_emissao = li_emissao.get_text()
                    partes = texto_emissao.split('Emissão:')
                    if len(partes) > 1:
                        texto_bruto = partes[1]
                        padrao_data_hora = r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}"
                        
                        match = re.search(padrao_data_hora, texto_bruto)

                        if match:
                            data_limpa = match.group(0)
                            nfce_data['data_compra'] = data_limpa



    # --- Extrair informações de totalização ---
    total_nota_div = soup.find('div', id='totalNota')
    if total_nota_div:
        # Acessar os elementos internos por suas labels
        nfce_data['qtd_total_itens'] = total_nota_div.find('label', string='Qtd. total de itens:').find_next_sibling('span').get_text(strip=True)
        nfce_data['valor_total'] = total_nota_div.find('label', string='Valor total R$:')
        if nfce_data['valor_total']: 
            nfce_data['valor_total'] = nfce_data['valor_total'].find_next_sibling('span').get_text(strip=True).replace(' ', '')
        nfce_data['desconto'] = total_nota_div.find('label', string='Descontos R$:')
        if nfce_data['desconto']:
            nfce_data['desconto'].find_next_sibling('span').get_text(strip=True).replace(' ', '')
        nfce_data['valor_pago'] = total_nota_div.find('div', class_='linhaShade').find('span', class_='totalNumb').get_text(strip=True).replace(' ', '')

    # --- Extrair a chave de acesso ---
        chave_span = soup.find('span', class_='chave')
        if chave_span:
            # Normalizar a chave de acesso, removendo espaços
            nfce_data['chave_acesso'] = chave_span.get_text(strip=True).replace(' ', '')

    # --- Extrair a lista de itens ---
    itens = []
    tabela_itens = soup.find('table', id='tabResult')
    if tabela_itens:
        # Encontrar todas as linhas da tabela (exceto o cabeçalho, se houver)
        linhas_tabela = tabela_itens.find_all('tr')
        for linha in linhas_tabela:
            colunas = linha.find_all('td')
            if len(colunas) > 0:
                # Extrair o nome, quantidade, unidade e valor unitário
                codigo_item = colunas[0].find('span', class_='RCod').get_text(strip=True).replace('(Código:', '').replace(')', '').strip()
                nome_item = colunas[0].find('span', class_='txtTit').get_text(strip=True)
                quantidade = colunas[0].find('span', class_='Rqtd').get_text(strip=True).replace('Qtde.:', '').replace(',', '.')
                unidade = colunas[0].find('span', class_='RUN').get_text(strip=True).replace('UN:', '')
                valor_unidade = colunas[0].find('span', class_='RvlUnit').get_text(strip=True).replace('Vl. Unit.:', '').replace(',', '.')

                # Extrair o valor total do item
                valor_total_item = colunas[1].find('span', class_='valor').get_text(strip=True).replace(',', '.')

                itens.append({
                    'codigo': codigo_item,
                    'nome': nome_item,
                    'quantidade': quantidade.strip(),
                    'tipo_unidade': unidade.strip(),
                    'preco_unidade': valor_unidade.strip(),
                    'preco_total': valor_total_item.strip(),
                    "chave_compra": nfce_data['chave_acesso']
                })
    nfce_data['itens'] = itens

    return nfce_data

def inserir_dados_nfce_bd(scrapped):
    """
    Insere os dados de uma compra e seus respectivos produtos no banco de dados.

    Esta função recebe um dicionário com os dados extraídos da NFC-e, formata
    a data da compra para o padrão ISO 8601 com fuso horário de São Paulo, 
    e então insere as informações gerais na tabela 'compra' e a lista de itens
    na tabela 'produto'.

    Args:
        scrapped (dict): Um dicionário contendo todas as informações extraídas
                         da nota fiscal, gerado pela função extrair_dados_nfce.

    Return:
        None: A função não retorna valores, apenas executa as operações de
              inserção no banco de dados.
    """

    resp = (supabase.table("compra").select('*').eq("chave", scrapped['chave_acesso']).execute())
    print(resp)
    if len(resp.data) == 0:
        data_hora_obj = datetime.strptime(scrapped['data_compra'], "%d/%m/%Y %H:%M:%S")
        string_iso_8601_com_tz = data_hora_obj.replace(tzinfo=ZoneInfo("America/Sao_Paulo")).isoformat()
        
        supabase.table("compra").insert({"chave": scrapped['chave_acesso'].replace(',', '.'), 
                    "data": string_iso_8601_com_tz, 
                    "valor_total": scrapped['valor_total'].replace(',', '.') if scrapped['valor_total'] else None, 
                    "desconto": scrapped['desconto'].replace(',', '.') if scrapped['desconto'] else None,
                    "valor_pago": scrapped['valor_pago'].replace(',', '.'),
                    "nome_comercio": scrapped['nome_comercio'],
                    "endereco": scrapped["endereco"],
                    "cnpj": scrapped['CNPJ']}).execute()
        
        supabase.table("produto").insert(scrapped['itens']).execute()
    else: 
        feedbacks.append({"code": 409, "message": "Nota ja existe."})
        raise ValueError("Nota ja existe.")
        

    