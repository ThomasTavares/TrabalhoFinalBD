# pip install mysql-connector-python openai pillow transformers torch scikit-learn requests
# Se possível usar VENV (virtualenv) para isolar as dependências do projeto
# Mude os dados da conexão com o MySQL (para usar o banco de dados local)

import re
import ast
import io
import time
import random
import json
from datetime import datetime
from prettytable import PrettyTable
from collections import defaultdict, deque
from urllib.parse import quote

import openai
import mysql.connector
from mysql.connector import errorcode
import requests

from PIL import Image, ImageDraw, ImageFont
import numpy as np

from sklearn.metrics.pairwise import cosine_similarity
from transformers import CLIPProcessor, CLIPModel
import torch

# Carrega o modelo e o processador CLIP
clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch16")
clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch16")


def get_openai_key():
    """
    Obtém a chave de API da OpenAI do ambiente ou de um arquivo de configuração.
    Retorna:
        str: Chave de API da OpenAI.
    """
    api_key_file = "C:\\Users\\thoma\\Documents\\GitHub\\openai_key.txt"  # Altere para o caminho do seu arquivo de chave
    with open(api_key_file, "r", encoding="utf-8") as f:
        api_key_value = f.read()
    return api_key_value


openai.api_key = get_openai_key()


def connect_mysql(host="localhost", user="root", password="", database=None, port=3306):
    """
    Conecta-se a um banco de dados MySQL e retorna o objeto de conexão.

    Parâmetros:
        host (str): Host do servidor MySQL.
        user (str): Usuário para autenticação.
        password (str): Senha para autenticação.
        database (str, opcional): Nome do banco de dados a ser utilizado.
        port (int): Porta do servidor MySQL.

    Retorna:
        mysql.connector.connection.MySQLConnection ou None: Objeto de conexão se bem-sucedido, caso contrário None.
    """
    try:
        cnx = mysql.connector.connect(
            host=host, user=user, password=password, database=database, port=port
        )

        if cnx is not None and cnx.is_connected():
            print(f"Conectado ao MySQL em {host}:{port}")
            if database:
                print(f"Banco de dados selecionado: {database}")
            else:
                print("Nenhum banco de dados selecionado.")
            return cnx
    except mysql.connector.Error as err:
        print("Erro ao conectar ao MySQL:", err)
    return None


def create_tables(conexao):
    """
    Cria tabelas em um banco de dados MySQL a partir de um arquivo SQL.
    Esta função lê um arquivo SQL contendo comandos DDL (Data Definition Language),
    remove comentários e executa cada comando separadamente na conexão fornecida.
    Ela trata erros comuns, como tentativa de criar tabelas já existentes e erros de sintaxe,
    exibindo mensagens informativas para cada situação.
    Parâmetros:
        arquivo_sql (str): Caminho para o arquivo .sql contendo os comandos de criação das tabelas.
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    with open("script.sql", "r", encoding="utf-8") as f:
        script = f.read()

    # Remove comentários --, # e /* */ (Só para garantir)
    script = re.sub(r"/\*.*?\*/", "", script, flags=re.DOTALL)
    linhas = script.splitlines()
    script_limpo = "\n".join(
        l for l in linhas if not l.strip().startswith(("--", "#")) and l.strip()
    )

    # Divide as execuções até ;
    comandos = script_limpo.split(";")

    cursor = conexao.cursor()

    # Executa todos os comandos do script DDL
    for i, comando in enumerate(comandos):
        comando = comando.strip()
        if comando:
            try:
                cursor.execute(comando)
                print(f"[{i+1:02}] Executado: {comando.split()[0].upper()} ...")
            except mysql.connector.Error as err:
                erro_tipo = type(err).__name__
                erro_num = err.errno

                if erro_num == errorcode.ER_TABLE_EXISTS_ERROR:
                    tabela_match = re.search(
                        r"CREATE TABLE\s+`?(\w+)`?", comando, re.IGNORECASE
                    )
                    nome_tabela = tabela_match.group(1) if tabela_match else "desconhecida"
                    print(f"[{i+1:02}] Tabela '{nome_tabela}' já existe.")
                elif erro_num == errorcode.ER_PARSE_ERROR:
                    print(f"[{i+1:02}] Erro de sintaxe SQL:\n{comando}\n→ {err}")
                else:
                    print(
                        f"[{i+1:02}] {erro_tipo} ({erro_num}) ao executar:\n{comando}\n→ {err}"
                    )

    conexao.commit()
    cursor.close()
    return None


def drop_tables(conexao):
    """
    Remove todas as tabelas do banco de dados conectado.

    Esta função desativa temporariamente as restrições de chave estrangeira,
    busca todas as tabelas existentes no banco de dados e remove cada uma delas.
    Após a remoção, as restrições de chave estrangeira são reativadas.

    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.

    Retorna:
        None
    """
    
    try:
        cursor = conexao.cursor()

        # Desativar restrições de chave estrangeira
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

        # Busca todas as tabelas
        cursor.execute("SHOW TABLES;")
        tabelas = cursor.fetchall()

        if not tabelas:
            print("Nenhuma tabela encontrada no banco.")
            return

        # Dropa as tabelas
        for (nome_tabela,) in tabelas:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS `{nome_tabela}`;")
                print(f"Tabela '{nome_tabela.upper()}' removida.")
            except mysql.connector.Error as e:
                print(f"Erro ao deletar tabela '{nome_tabela.upper()}': {e}")

        # Reativa as restrições
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        conexao.commit()
        cursor.close()

    except mysql.connector.Error as e:
        print("Erro ao deletar tabelas:", e)


def print_tables(conexao, print_flag=True):
    """
    Exibe as tabelas disponíveis no banco de dados conectado.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        dict: Um dicionário onde as chaves são os nomes das tabelas em minúsculo e os valores são os nomes reais das tabelas.
    """
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES;")
    resultado = cursor.fetchall()

    if not resultado:
        print("Nenhuma tabela encontrada.")
        return {}

    tabelas = {t[0].lower(): t[0] for t in resultado}

    if print_flag:
        for nome_real in tabelas.values():
            print(f"• {nome_real.upper()}")

    cursor.close()
    
    return tabelas


def show_table(conexao, tabela):
    """
    Exibe os valores registrados em uma tabela específica do banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
        tabela (str): Nome da tabela a ser exibida.
    Retorna:
        int: Número de linhas exibidas na tabela, ou 0 se a tabela estiver vazia.
    """
    cursor = conexao.cursor()
    
    tabelas = print_tables(conexao, False)
    
    if tabela not in tabelas:
        print(f"Tabela '{tabela.upper()}' não encontrada.")
        cursor.close()
        return

    try:
        cursor.execute(f"SELECT * FROM `{tabela}`")
        linhas = cursor.fetchall()
        tabela_formatada = PrettyTable()
        tabela_formatada.field_names = [col[0] for col in cursor.description]
        if linhas:
            for linha in linhas:
                tabela_formatada.add_row(linha)
            print(tabela_formatada)
        else:
            print(f"A tabela '{tabela.upper()}' está vazia.")
    except mysql.connector.Error as err:
        print(f"Erro ao consultar: {err}")
    finally:
        cursor.close()
    
    # Retorna o número de linhas exibidas
    return len(linhas)


def show_tables(conexao):
    """
    Exibe as tabelas disponíveis no banco de dados conectado e permite ao usuário consultar o conteúdo de uma tabela específica.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
    Retorna:
        None
    """
    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")

    # Mostra todas as tabelas
    tabelas = print_tables(conexao)

    # Entrada do usuário
    entrada = input("\nDigite o nome da tabela que deseja consultar: ").strip().lower()
    
    # Verificar se entrada existe antes de acessar
    if entrada not in tabelas:
        print(f"Tabela '{entrada.upper()}' não encontrada.")
        return
    
    nome_real = tabelas[entrada]
    print(f"\nTabela: {nome_real.upper()}")
    show_table(conexao, nome_real)
    
    print("\n" + "="*50)


def get_schema_info(conexao):
    """
    Obtém informações do schema de todas as tabelas do banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
    Retorna:
        dict: Um dicionário onde as chaves são os nomes das tabelas e os valores são listas de dicionários
              contendo o nome e o tipo de cada coluna da tabela.
    """
    
    # Obtém o schema de todas as tabelas no banco de dados
    schema = {}
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas = [linha[0] for linha in cursor.fetchall()]

    # Para cada tabela, obtém as colunas e seus tipos
    for tabela_nome in tabelas:
        cursor.execute(f"DESCRIBE `{tabela_nome}`")
        colunas = cursor.fetchall()
        schema[tabela_nome] = [{"nome": col[0], "tipo": col[1]} for col in colunas]

    cursor.close()
    return schema


def build_prompt(schema: dict, tabela_alvo: str, n_linhas=20):
    """
    Gera um prompt para criação de dados fictícios para uma tabela específica de um schema.
    NOTA: Para tabela Midia, use build_prompt_for_media_table() para tratamento especial de BLOB.
    """
    with open("script.sql", "r", encoding="utf-8") as f:
        script = f.read()
    
    # Monta informações detalhadas sobre o contexto do banco
    contexto_banco = """
    CONTEXTO DO BANCO DE DADOS:
    Este é um sistema de gerenciamento para um laboratório de taxonomia que lida com:
    - Classificação taxonômica de espécies (Domínio → Reino → Filo → Classe → Ordem → Família → Gênero → Espécie)
    - Espécimes e amostras biológicas coletadas
    - Projetos de pesquisa científica e artigos publicados
    - Funcionários, laboratórios e equipamentos
    - Financiamentos e contratos
    - Mídia (imagens, áudios) dos espécimes
    """
    
    # Informações específicas sobre a tabela alvo
    if tabela_alvo in schema:
        campos_info = []
        for col in schema[tabela_alvo]:
            tipo_col = col['tipo']
            # Tratamento especial para campos BLOB
            if 'blob' in tipo_col.lower():
                campos_info.append(f"- {col['nome']}: {tipo_col} (sempre null no JSON)")
            else:
                campos_info.append(f"- {col['nome']}: {tipo_col}")
        campos_str = "\n".join(campos_info)
    else:
        campos_str = "Tabela não encontrada no schema"
    
    # Instruções específicas por tabela para dados mais realistas
    instrucoes_especificas = {
        'Taxon': 'Use nomes taxonômicos reais (ex: Animalia, Chordata, Mammalia, etc.). IDs sequenciais começando em 1.',
        'Hierarquia': 'Respeite a hierarquia taxonômica: Domínio(1) → Reino(2) → Filo(3) → etc.',
        'Especie': 'Use nomes científicos reais de espécies (ex: Homo sapiens, Canis lupus). IUCN: LC, NT, VU, EN, CR, EW, EX.',
        'Especime': 'Descritivos como "Espécime adulto macho", "Jovem fêmea", "Esqueleto completo".',
        'Local_de_Coleta': 'Use locais reais como "Floresta Amazônica", "Mata Atlântica", "Cerrado".',
        'Amostra': 'Tipos: sangue, pele, osso, DNA, fezes, pelo, escama, etc.',
        'Projeto': 'Nomes científicos realistas, status atual dos projetos.',
        'Funcionario': 'Nomes brasileiros, CPFs válidos (11 dígitos), cargos: Pesquisador, Técnico, Bolsista, etc.',
        'Laboratorio': 'Nomes como "Lab. de Genética", "Lab. de Taxonomia", endereços de universidades.',
        'Financiador': 'Órgãos como CNPq, CAPES, FAPESP, universidades.',
        'Equipamento': 'Microscópios, sequenciadores, centrífugas, etc.',
        'Midia': 'ATENÇÃO: Use build_prompt_for_media_table() para esta tabela. Campo BLOB sempre null.'
    }
    
    instrucao_tabela = instrucoes_especificas.get(tabela_alvo, 'Gere dados realistas e coerentes.')
    
    prompt = f"""
    {contexto_banco}
    
    SCHEMA COMPLETO DO BANCO:
    {script}
    
    TABELA ALVO: {tabela_alvo}
    Campos da tabela:
    {campos_str}
    
    INSTRUÇÕES ESPECÍFICAS:
    {instrucao_tabela}
    
    TAREFA:
    Gere exatamente {n_linhas} registros realistas para a tabela `{tabela_alvo}` considerando o contexto científico do laboratório de taxonomia.
    
    FORMATO DE RESPOSTA (OBRIGATÓRIO):
    Retorne APENAS um objeto JSON válido no seguinte formato:
    {{
        "registros": [
            {{"campo1": valor1, "campo2": valor2, ...}},
            {{"campo1": valor1, "campo2": valor2, ...}},
            ...
        ]
    }}
    
    REGRAS IMPORTANTES:
    - Use valores apropriados para cada tipo de campo (int, varchar, date, decimal)
    - Para campos de data, use formato 'YYYY-MM-DD'
    - Para campos decimais, use números com até 2 casas decimais
    - Para varchar, respeite os limites de caracteres
    - Para campos BLOB, use null (dados binários não podem ser gerados em JSON)
    - IDs devem ser sequenciais começando em 1
    - Mantenha coerência entre dados relacionados
    
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    """
    return prompt.strip()


def build_prompt_for_media_table(schema: dict, tabela_alvo: str, n_linhas=20):
    """
    Gera um prompt específico para a tabela Midia (com campos BLOB).
    Esta função garante que campos BLOB sejam sempre null no JSON,
    evitando que a IA tente gerar dados binários aleatórios.
    """
    if tabela_alvo.lower() != 'midia':
        return build_prompt(schema, tabela_alvo, n_linhas)
    
    prompt = f"""
    CONTEXTO: Sistema de laboratório de taxonomia - Tabela de mídia para armazenar imagens/áudios de espécimes.
    
    IMPORTANTE: NÃO gere dados para o campo BLOB. Sempre use null.
    
    Gere {n_linhas} registros JSON para a tabela Midia:
    - ID_Midia: integer (sequencial começando em 1)
    - ID_Especime: integer (referência aos espécimes existentes, use valores 1-{min(10, n_linhas)})
    - Tipo: varchar(50) (exemplos: "Fotografia dorsal", "Microscopia 40x", "Áudio de vocalização", "Imagem lateral", "Video comportamental")
    - Dado: blob (SEMPRE null no JSON - as imagens serão inseridas separadamente)
    
    FORMATO DE RESPOSTA:
    {{
        "registros": [
            {{"ID_Midia": 1, "ID_Especime": 1, "Tipo": "Fotografia lateral", "Dado": null}},
            {{"ID_Midia": 2, "ID_Especime": 2, "Tipo": "Microscopia 100x", "Dado": null}},
            ...
        ]
    }}
    
    REGRAS:
    - Varie os tipos de mídia (fotografia, microscopia, áudio, vídeo)
    - IDs sequenciais começando em 1
    - Campo Dado sempre null
    - ID_Especime deve referenciar espécimes existentes
    
    Responda SOMENTE com o JSON, sem explicações.
    """
    return prompt.strip()


def insert_data_from_json(conexao, nome_tabela, json_dados):
    """
    Insere dados em uma tabela a partir de um JSON estruturado.
    Parâmetros:
        conexao: Conexão com o banco de dados.
        nome_tabela (str): Nome da tabela.
        json_dados (dict): Dados em formato JSON com chave "registros".
    """
    if "registros" not in json_dados:
        raise ValueError("JSON deve conter a chave 'registros'")
    
    registros = json_dados["registros"]
    if not registros:
        print(f"Nenhum registro para inserir na tabela {nome_tabela}")
        return
    
    # Pega os campos do primeiro registro
    campos = list(registros[0].keys())
    
    # Obtém o schema da tabela para verificar os tamanhos máximos das colunas
    cursor = conexao.cursor()
    cursor.execute(f"DESCRIBE `{nome_tabela}`")
    colunas_detalhes = cursor.fetchall()
    schema_colunas = {col[0]: col[1] for col in colunas_detalhes}  # Mapeia nome da coluna para tipo

    placeholders = ", ".join(["%s"] * len(campos))
    campos_sql = ", ".join([f"`{c}`" for c in campos])
    insert_query = f"INSERT INTO `{nome_tabela}` ({campos_sql}) VALUES ({placeholders})"
    
    sucessos = 0
    erros = 0
    
    for registro in registros:
        try:
            # Trunca os valores com base no tamanho máximo permitido no schema
            valores = []
            for campo in campos:
                valor = registro[campo]
                if campo in schema_colunas and "varchar" in schema_colunas[campo].lower():
                    # Extrai o tamanho máximo do varchar
                    max_len_match = re.search(r'varchar\((\d+)\)', schema_colunas[campo].lower())
                    if max_len_match:
                        max_len = int(max_len_match.group(1))
                        valor = truncate_value(valor, max_len)
                valores.append(valor)
            
            # Executa a inserção
            cursor.execute(insert_query, tuple(valores))
            sucessos += 1
        except mysql.connector.Error as err:
            print(f"Erro ao inserir registro {registro}: {err}")
            erros += 1
    
    conexao.commit()
    cursor.close()
    
    print(f"Tabela {nome_tabela}: {sucessos} inserções bem-sucedidas, {erros} erros")


def populate_all_tables(conexao, n_linhas=10):
    """
    Popula todas as tabelas usando o novo formato JSON.
    """

    schema = get_schema_info(conexao)
    ordem = ["taxon", "hierarquia", "especie", "especime", 
            "local_de_coleta", "amostra", "midia", "projeto", 
            "artigo", "funcionario", "proj_func", "proj_esp", 
            "categoria", "proj_cat", "laboratorio", "contrato", 
            "financiador", "financiamento", "equipamento", 
            "registro_de_uso"]
    
    cursor = conexao.cursor()
    cursor.execute("SHOW TABLES")
    tabelas = [linha[0] for linha in cursor.fetchall()]
    cursor.close()
    
    # Filtra apenas tabelas que existem no banco
    tabelas_ordenadas = [t for t in ordem if t in tabelas]

    for tabela_nome in tabelas_ordenadas:
        print(f"\nProcessando tabela: `{tabela_nome.upper()}`")
        
        try:
            cursor = conexao.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{tabela_nome}`")
            total = cursor.fetchone()[0]
            cursor.close()
            
            if total > 0:
                print(f"Tabela `{tabela_nome.upper()}` já contém {total} registros. Pulando...")
                continue
            
            # TRATAMENTO ESPECIAL PARA TABELA TAXON
            if tabela_nome.lower() == 'taxon':
                print("  → Tratamento especial para a tabela `Taxon`...")
                populate_taxon_table(conexao)
                continue

            # TRATAMENTO ESPECIAL PARA TABELA MIDIA
            if tabela_nome.lower() == 'midia':
                print("  → Preenchendo tabela `Midia` com imagens reais...")
                populate_midia_table(conexao)
                continue

            # GERAR DADOS VIA IA PARA OUTRAS TABELAS
            # Escolhe o prompt adequado baseado na tabela
            if tabela_nome.lower() == 'midia':
                # Caso especial se não usar populate_midia_table
                prompt = build_prompt_for_media_table(schema, tabela_nome, n_linhas)
            else:
                prompt = build_prompt(schema, tabela_nome, n_linhas)
            
            print(f"  → Gerando {n_linhas} registros via IA...")
            resposta = generate_data(prompt)
            
            try:
                # Parse do JSON
                dados_json = json.loads(resposta)
                insert_data_from_json(conexao, tabela_nome, dados_json)
                print(f"✓ Tabela `{tabela_nome.upper()}` populada com sucesso")
                
            except json.JSONDecodeError as e:
                print(f"Erro ao fazer parse do JSON para `{tabela_nome}`: {e}")
                print(f"Resposta recebida: {resposta[:200]}...")
                continue
            except ValueError as e:
                print(f"Erro nos dados para `{tabela_nome}`: {e}")
                continue
                
        except (mysql.connector.Error, ValueError, json.JSONDecodeError) as e:
            print(f"Erro ao processar `{tabela_nome}`: {e}")
            continue


def generate_data(prompt, modelo="gpt-4o-mini", temperatura=0.4):
    """     
        Gera dados a partir de um prompt utilizando um modelo da OpenAI.
        Parâmetros:
            prompt (str): Texto de entrada que será enviado ao modelo para geração de dados.
            modelo (str, opcional): Nome do modelo OpenAI a ser utilizado. Padrão é "gpt-4o-mini".
            temperatura (float, opcional): Grau de aleatoriedade na geração do texto. Padrão é 0.4.
        Retorna:
            str: Texto gerado pelo modelo OpenAI em resposta ao prompt fornecido.
    """

    # Gera dados usando o modelo OpenAI
    response = openai.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperatura,
    )
    return response.choices[0].message.content


def insert_data(conexao, nome_tabela, campos, dados):
    """
    Wrapper para insert_data_from_json - converte dados de tupla para JSON.
    """
    # Converte lista de tuplas para formato JSON
    registros = []
    for linha in dados:
        registro = {campo: valor for campo, valor in zip(campos, linha)}
        registros.append(registro)
    
    json_dados = {"registros": registros}
    return insert_data_from_json(conexao, nome_tabela, json_dados)


def search_image_web(nome_especie, timeout=10):
    """
    Busca uma imagem na web baseada no nome da espécie.
    Parâmetros:
        nome_especie (str): Nome da espécie para buscar imagem.
        timeout (int): Timeout para a requisição HTTP.
    Retorna:
        bytes ou None: Bytes da imagem se encontrada, None caso contrário.
    """
    try:
        # Usando Lorem Picsum com seed baseada no nome da espécie para consistência
        seed = hash(nome_especie) % 1000
        url = f"https://picsum.photos/400/300?random={seed}"
        
        response = requests.get(url, timeout=timeout)
        if response.status_code == 200:
            return response.content
            
    except requests.RequestException as e:
        print(f"Erro de requisição ao buscar imagem para '{nome_especie}': {e}")
    except Exception as e:
        print(f"Erro inesperado ao buscar imagem para '{nome_especie}': {e}")
    
    return None


def create_placeholder_image(nome_especie, tamanho=(400, 300)):
    """
    Cria uma imagem placeholder com o nome da espécie.
    Parâmetros:
        nome_especie (str): Nome da espécie.
        tamanho (tuple): Dimensões da imagem (largura, altura).
    Retorna:
        bytes: Bytes da imagem PNG gerada.
    """
    try:
        # Cria uma imagem com cor baseada no hash do nome
        cor_base = hash(nome_especie) % 0xFFFFFF
        cor_rgb = ((cor_base >> 16) & 255, (cor_base >> 8) & 255, cor_base & 255)
        
        # Torna a cor mais suave
        cor_rgb = tuple(min(255, max(50, c + 100)) for c in cor_rgb)
        
        img = Image.new('RGB', tamanho, color=cor_rgb)
        draw = ImageDraw.Draw(img)
        
        # Adiciona texto com o nome da espécie
        try:
            # Tenta usar uma fonte do sistema
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
        except:
            # Fallback para fonte padrão
            font = ImageFont.load_default()
        
        # Calcula posição central do texto
        bbox = draw.textbbox((0, 0), nome_especie, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (tamanho[0] - text_width) // 2
        y = (tamanho[1] - text_height) // 2
        
        # Desenha o texto
        draw.text((x, y), nome_especie, fill='white', font=font)
        
        # Converte para bytes
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()
        
    except (OSError, IOError) as e:
        print(f"Erro ao criar placeholder para '{nome_especie}': {e}")
        return None


def populate_taxon_table(conexao):
    """
    Popula a tabela Taxon com a taxonomia completa para as espécies.
    """
    schema = get_schema_info(conexao)
    if 'taxon' not in schema:
        print("Tabela `TAXON` não encontrada no banco de dados.")
        return

    # Gera o prompt para preencher toda a taxonomia
    prompt = """
    Gere uma taxonomia completa para espécies fictícias. A taxonomia deve incluir os seguintes níveis:
    - Domínio
    - Reino
    - Filo
    - Classe
    - Ordem
    - Família
    - Gênero

    Cada nível deve ser coerente com o anterior. Retorne os dados no seguinte formato JSON:
    {
        "registros": [
            {"ID_Tax": 1, "Tipo": "Domínio", "Nome": "Eukaryota"},
            {"ID_Tax": 2, "Tipo": "Reino", "Nome": "Animalia"},
            {"ID_Tax": 3, "Tipo": "Filo", "Nome": "Chordata"},
            {"ID_Tax": 4, "Tipo": "Classe", "Nome": "Mammalia"},
            {"ID_Tax": 5, "Tipo": "Ordem", "Nome": "Primates"},
            {"ID_Tax": 6, "Tipo": "Família", "Nome": "Hominidae"},
            {"ID_Tax": 7, "Tipo": "Gênero", "Nome": "Homo"}
        ]
    }
    Responda SOMENTE com o JSON, sem explicações ou texto adicional.
    """
    print("  → Gerando taxonomia completa via IA...")
    resposta = generate_data(prompt)

    # Valida a resposta antes de processar
    if not resposta.strip():
        print("Erro: Resposta da IA está vazia.")
        return

    try:
        # Parse do JSON
        dados_json = json.loads(resposta)
        registros = dados_json.get("registros", [])
        if not registros:
            print("Nenhum registro gerado para a tabela `Taxon`.")
            return

        # Insere os dados na tabela Taxon
        cursor = conexao.cursor()
        for registro in registros:
            query = "INSERT INTO Taxon (ID_Tax, Tipo, Nome) VALUES (%s, %s, %s)"
            valores = (registro["ID_Tax"], registro["Tipo"], registro["Nome"])
            cursor.execute(query, valores)

        conexao.commit()
        cursor.close()
        print("✓ Tabela `Taxon` populada com sucesso")
    except json.JSONDecodeError as e:
        print(f"Erro ao fazer parse do JSON para `Taxon`: {e}")
        print(f"Resposta recebida: {resposta[:200]}...")
    except mysql.connector.Error as e:
        print(f"Erro ao inserir dados na tabela `Taxon`: {e}")


def populate_midia_table(conexao, delay_entre_requisicoes=2):
    """
    Popula a tabela Midia com imagens REAIS buscadas na web
    baseadas nos nomes das espécies cadastradas no banco.
    
    Esta função evita inserir dados aleatórios no campo BLOB,
    buscando imagens reais ou criando placeholders específicos.
    """
    cursor = conexao.cursor()
    
    try:
        # Verifica se a tabela Midia já tem dados
        cursor.execute("SELECT COUNT(*) FROM Midia")
        count = cursor.fetchone()[0]
        if count > 0:
            print(f"Tabela Midia já contém {count} registros. Pulando...")
            return
        
        # Busca todas as espécies cadastradas
        cursor.execute("SELECT ID_Esp, Nome FROM Especie")
        especies = cursor.fetchall()
        
        if not especies:
            print("Nenhuma espécie encontrada. Popule a tabela Especie primeiro.")
            print("   Use a opção 7 para popular as tabelas na ordem correta.")
            return
        
        print(f"✓ Encontradas {len(especies)} espécies. Buscando imagens REAIS...")
        
        sucessos = 0
        falhas = 0
        
        for idx, (id_esp, nome_especie) in enumerate(especies, 1):
            print(f"[{idx}/{len(especies)}] Processando: {nome_especie}")
            
            # Primeiro tenta buscar imagem real na web
            especie_imagem_bytes = search_image_web(nome_especie)
            
            # Se não conseguir, cria um placeholder ESPECÍFICO (não aleatório)
            if not especie_imagem_bytes:
                print(f"  → Criando placeholder específico para '{nome_especie}'")
                especie_imagem_bytes = create_placeholder_image(nome_especie)
            else:
                print(f"  → ✓ Imagem real encontrada na web para '{nome_especie}'")
            
            if especie_imagem_bytes:
                try:
                    # Busca um espécime desta espécie para associar à mídia
                    cursor.execute(
                        "SELECT ID_Especime FROM Especime WHERE ID_Esp = %s LIMIT 1",
                        (id_esp,)
                    )
                    especime = cursor.fetchone()
                    
                    if especime:
                        id_especime = especime[0]
                        # Insere na tabela Midia (ID_Midia é AUTO_INCREMENT)
                        cursor.execute(
                            "INSERT INTO Midia (ID_Especime, Tipo, Dado) VALUES (%s, %s, %s)",
                            (id_especime, f"Imagem - {nome_especie}", especie_imagem_bytes)
                        )
                        
                        # Pega o ID da mídia inserida
                        id_midia = cursor.lastrowid
                        
                        sucessos += 1
                        print(f"  → ✓ Sucesso! ID_Midia: {id_midia}")
                    else:
                        print(f"  → Nenhum espécime encontrado para '{nome_especie}'")
                        falhas += 1
                    
                except mysql.connector.Error as e:
                    print(f"  → Erro ao inserir mídia para '{nome_especie}': {e}")
                    falhas += 1
            else:
                print(f"  → Não foi possível obter imagem para '{nome_especie}'")
                falhas += 1
            
            # Delay para não sobrecarregar APIs
            if idx < len(especies):  # Não faz delay na última iteração
                time.sleep(delay_entre_requisicoes)
        
        conexao.commit()
        print(f"\n{'='*60}")
        print("PROCESSAMENTO DA TABELA MIDIA CONCLUÍDO:")
        print(f"   • ✓ Sucessos: {sucessos}")
        print(f"   • Falhas: {falhas}")
        print(f"   • Total processado: {len(especies)}")
        print(f"   • Taxa de sucesso: {(sucessos/len(especies)*100):.1f}%")
        print(f"{'='*60}")
        
    except mysql.connector.Error as e:
        print(f"Erro de banco de dados ao popular tabela Midia: {e}")
        conexao.rollback()
    except OSError as e:
        print(f"Erro de sistema ao popular tabela Midia: {e}")
    finally:
        cursor.close()


def truncate_value(value, max_length):
    if isinstance(value, str) and len(value) > max_length:
        return value[:max_length]
    return value


def check_ckeck(conexao, tabela):
    '''
    Verifica se a tabela possui CHECK constraints
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    Retorna:
        list: Lista de tuplas contendo o nome da constraint e a cláusula CHECK. Se não houver constraints, retorna uma lista vazia.
    '''
    cursor = conexao.cursor()
    
    query = """
    SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE
    FROM information_schema.check_constraints cc
    JOIN information_schema.table_constraints tc
    ON cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
    WHERE tc.TABLE_NAME = %s AND tc.TABLE_SCHEMA = %s AND tc.CONSTRAINT_TYPE = 'CHECK';
    """
    cursor.execute(query, (tabela, conexao.database))
    resultado = cursor.fetchall()
    
    if resultado:
        for constraint in resultado:
            print(f"Valores permitidos para {constraint[0]}: {constraint[1]}")
    cursor.close()
    
    return resultado


def insert_by_user(conexao):
    """
    Solicita ao usuário o nome da tabela, os campos e valores a serem inseridos, e realiza a operação.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")
    cursor = conexao.cursor()

    # Exibe tabelas disponíveis
    tabelas = print_tables(conexao)

    # Solicita nome da tabela
    tabela_nome = input("\nDigite o nome da tabela para inserir dados: ").strip().lower()
    
    if tabela_nome not in tabelas:
        print(f"Tabela `{tabela_nome.upper()}` não encontrada.")
        cursor.close()
        return

    # Exibe colunas da tabela selecionada
    cursor.execute(f"DESCRIBE `{tabela_nome}`")
    colunas_detalhadas = cursor.fetchall()
    colunas = [col[0] for col in colunas_detalhadas]
    
    print(f"\nTabela selecionada: {tabela_nome.upper()}")
    print("Colunas disponíveis:")
    for i, col_info in enumerate(colunas_detalhadas, 1):
        nome_col = col_info[0]
        tipo_col = col_info[1]
        null_col = col_info[2]
        key_col = col_info[3]
        
        # Indica se é obrigatório
        obrigatorio = "OBRIGATÓRIO" if null_col == 'NO' and key_col != 'PRI' else ""
        auto_increment = "AUTO_INCREMENT" if 'auto_increment' in str(col_info).lower() else ""
        
        status = []
        if key_col == 'PRI':
            status.append("PK")
        if auto_increment:
            status.append("AI")
        if obrigatorio:
            status.append("OBRIGATÓRIO")
        
        status_str = f" [{', '.join(status)}]" if status else ""
        print(f"\t• {nome_col}: {tipo_col}{status_str}")
    
    # Exibe valores já registrados na tabela
    print("\nValores registrados:")
    show_table(conexao, tabela_nome)

    # Coleta valores para cada campo
    print("\nPreencha os valores para cada campo (digite 'null' para deixar campo vazio):")
    valores = []
    for campo in colunas:
        # Busca informações do campo
        campo_info = next((col for col in colunas_detalhadas if col[0] == campo), None)
        tipo_campo = campo_info[1] if campo_info else "unknown"
        
        if 'timestamp' in tipo_campo.lower():
            valor = (datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
            print(f"• {campo} ({tipo_campo}): {valor} [AUTO-GERADO]")
        elif 'blob' in tipo_campo.lower():
            valor_input = input(f"• {campo} ({tipo_campo}). Digite o caminho do arquivo: ").strip()
            if valor_input.lower() == 'null' or valor_input == '':
                valor = None
            else:
                try:
                    with open(valor_input, 'rb') as f:
                        valor = f.read()
                except FileNotFoundError:
                    print(f"Arquivo '{valor_input}' não encontrado. Usando valor None.")
                    valor = None
        else:
            valor_input = input(f"• {campo} ({tipo_campo}): ").strip()
            
            # CORRIGINDO: processamento do valor baseado no tipo
            if valor_input.lower() == 'null' or valor_input == '':
                valor = None
            elif 'int' in tipo_campo.lower():
                try:
                    valor = int(valor_input)
                except ValueError:
                    print(f"Valor inválido para {campo}. Usando 0.")
                    valor = 0
            elif 'decimal' in tipo_campo.lower() or 'float' in tipo_campo.lower():
                try:
                    valor = float(valor_input)
                except ValueError:
                    print(f"Valor inválido para {campo}. Usando 0.0.")
                    valor = 0.0
            elif 'date' in tipo_campo.lower():
                # Verifica se a data está no formato YYYY-MM-DD
                if re.match(r'^\d{4}-\d{2}-\d{2}$', valor_input):
                    valor = valor_input
                else:
                    print(f"Formato de data inválido para {campo}. Usando data atual.")
                    valor = (datetime.now()).strftime('%Y-%m-%d')
            elif 'varchar' in tipo_campo.lower():
                # Extrai o tamanho máximo do varchar
                match = re.search(r'varchar\((\d+)\)', tipo_campo.lower())
                if match:
                    max_len = int(match.group(1))
                    if len(valor_input) > max_len:
                        print(f"Valor para {campo} excede o tamanho máximo de {max_len} caracteres. Truncando.")
                        valor = valor_input[:max_len]
                    else:
                        valor = valor_input
                else:
                    valor = valor_input
            else:
                valor = valor_input
        
        valores.append(valor)

    # Confirma inserção
    print("\n" + "="*50)
    print("\nResumo da inserção:")
    print(f"Tabela: {tabela_nome.upper()}")
    for campo, valor in zip(colunas, valores):
        print(f"\t• {campo}: {valor}")

    confirmacao = input("\nConfirmar inserção? (s/N): ").strip().lower()
    if confirmacao not in ['s', 'sim', 'y', 'yes']:
        print("Inserção cancelada.")
        cursor.close()
        return

    # Insere os dados
    try:
        insert_data(conexao, tabela_nome, colunas, [tuple(valores)])
        print("Dados inseridos com sucesso!")
    except (mysql.connector.Error, ValueError) as e:
        print(f"Erro ao inserir dados: {e}")
    finally:
        cursor.close()
    print("\n" + "="*50)


def update_random_rows(conexao, tabela_nome, n_linhas=5, modelo="gpt-4o-mini", temperatura=0.4):
    """
    Atualiza aleatoriamente um número especificado de linhas em uma tabela de banco de dados com novos valores realistas, utilizando um modelo de IA para gerar os dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados MySQL.
        tabela_nome (str): Nome da tabela cujas linhas serão atualizadas.
        n_linhas (int, opcional): Número de linhas aleatórias a serem atualizadas. Padrão é 5.
        modelo (str, opcional): Nome do modelo de IA a ser utilizado para gerar os novos dados. Padrão é "gpt-4o-mini".
        temperatura (float, opcional): Temperatura do modelo de IA, controlando a aleatoriedade das respostas. Padrão é 0.4.
    """
    
    schema = get_schema_info(conexao)
    if tabela_nome not in schema:
        print(f"Tabela `{tabela_nome}` não encontrada.")
        return

    cursor = conexao.cursor(dictionary=True)
    cursor.execute(f"SELECT * FROM `{tabela_nome}` ORDER BY RAND() LIMIT {n_linhas}")
    linhas = cursor.fetchall()
    cursor.close()

    if not linhas:
        print(f"Tabela `{tabela_nome}` está vazia. Nada para atualizar.")
        return

    campos_str = "\n".join(
        f"- `{col['nome']}`: {col['tipo']}" for col in schema[tabela_nome]
    )

    for idx, linha in enumerate(linhas, start=1):
        prompt = f"""
            Atualize os dados da seguinte linha na tabela `{tabela_nome}` com novos valores realistas e diferentes, mantendo a estrutura do schema:

            {campos_str}

            Linha original:
            {linha}

            Gere a nova linha como um dicionário Python, com os mesmos campos e valores atualizados. A chave primária deve manter o mesmo valor.
        """
        resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
        try:
            nova_linha = ast.literal_eval(resposta)
            update_query = ", ".join(
                [f"`{k}` = %s" for k in nova_linha if k != list(linha.keys())[0]]
            )
            where = f"`{list(linha.keys())[0]}` = %s"
            valores = [nova_linha[k] for k in nova_linha if k != list(linha.keys())[0]]
            valores.append(linha[list(linha.keys())[0]])

            cursor = conexao.cursor()
            cursor.execute(
                f"UPDATE `{tabela_nome}` SET {update_query} WHERE {where}", valores
            )
            conexao.commit()
            cursor.close()
            print(f"Linha {idx}/{n_linhas} de `{tabela_nome}` atualizada com sucesso.")
        except (ValueError, SyntaxError) as e:
            print(
                f"Erro ao interpretar resposta da IA na linha {idx} → {e}"
            )
        except mysql.connector.Error as e:
            print(
                f"Erro ao executar o update na linha {idx} → {e}"
            )


def delete_random_rows(conexao, tabela_nome, n_linhas=5):
    """
    Remove aleatoriamente um número especificado de linhas de uma tabela em um banco de dados MySQL.
    Esta função identifica a chave primária da tabela fornecida, seleciona aleatoriamente `n_linhas` registros
    e os deleta da tabela. Caso a tabela não possua chave primária ou esteja vazia, a função exibe uma mensagem
    apropriada e não realiza nenhuma exclusão.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
        tabela_nome (str): Nome da tabela de onde as linhas serão removidas.
        n_linhas (int, opcional): Número de linhas a serem deletadas aleatoriamente. Padrão é 5.
    Retorna:
        None  
    """
    cursor = conexao.cursor()

    # Descobre a chave primária
    cursor.execute(
        """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_KEY = 'PRI'
        """,
        (tabela_nome,),
    )
    pk = cursor.fetchone()
    if not pk:
        print(f"Não foi possível identificar a chave primária da tabela `{tabela_nome}`.")
        cursor.close()
        return
    pk_col = pk[0]

    # Busca valores aleatórios
    cursor.execute(
        f"SELECT `{pk_col}` FROM `{tabela_nome}` ORDER BY RAND() LIMIT {n_linhas}"
    )
    pk_vals = cursor.fetchall()
    if not pk_vals:
        print(f"Tabela `{tabela_nome}` está vazia.")
        cursor.close()
        return

    deletados = 0
    for (pk_val,) in pk_vals:
        cursor.execute(f"DELETE FROM `{tabela_nome}` WHERE `{pk_col}` = %s", (pk_val,))
        deletados += 1

    conexao.commit()
    cursor.close()
    print(f"{deletados} linha(s) deletada(s) de `{tabela_nome}`.")


def update_by_user(conexao):
    """
    Solicita ao usuário o nome da tabela, o campo a ser atualizado, o novo valor e uma condição WHERE,
    depois executa uma operação UPDATE na tabela especificada usando os parâmetros fornecidos.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    cursor = conexao.cursor()

    print("\n" + "="*50)
    print("\nTabelas Disponíveis:")
    print_tables(conexao)
    
    tabela_nome = input("\nSelecione a Tabela: ").strip().lower()
    
    print("\nValores registrados:")
    num_linhas = show_table(conexao, tabela_nome)
    cursor.close()
    
    if num_linhas == 0:
        return

    campo = input("\nCampo a atualizar: ").strip()
    valor = input("Novo valor: ").strip()
    condicao = input("Insira a condição WHERE (ex: id = 1): ").strip()

    query = f"UPDATE `{tabela_nome}` SET `{campo}` = %s WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query, (valor,))
        conexao.commit()
        cursor.close()
        print("Atualização feita com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")
    print("\n" + "="*50)


def delete_by_user(conexao):
    """
    Deleta linhas de uma tabela do banco de dados com base em uma condição fornecida pelo usuário.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
    """
    print("\n" + "="*50)
    print_tables(conexao)
    
    tabela_nome = input("\nSelecione a Tabela: ").strip().lower()
    
    print("\nValores registrados:")
    show_table(conexao, tabela_nome)
    
    condicao = input("\nInsira a condição WHERE (ex: id = 1): ").strip()

    query = f"DELETE FROM `{tabela_nome}` WHERE {condicao}"
    try:
        cursor = conexao.cursor()
        cursor.execute(query)
        conexao.commit()
        cursor.close()
        print("\nLinhas deletadas com sucesso.")
    except mysql.connector.Error as err:
        print(f"Erro: {err}")
    print("\n" + "="*50)


def generate_sql_query(user_prompt, schema, modelo="gpt-4o-mini", temperatura=0.3):
    """
    Gera uma query SQL baseada em um pedido do usuário.
    """
    # Identifica tabelas mencionadas
    texto = user_prompt.lower()
    tabelas_relevantes = []
    
    # Palavras-chave que podem indicar tabelas mesmo sem mencionar o nome exato
    palavras_chave_tabela = {
        'especie': ['Especie', 'Especime'],
        'taxonomia': ['Taxon', 'Hierarquia', 'Especie'],
        'projeto': ['Projeto', 'Artigo', 'Proj_Func', 'Proj_Esp', 'Proj_Cat'],
        'funcionario': ['Funcionario', 'Contrato', 'Proj_Func'],
        'laboratorio': ['Laboratorio', 'Equipamento', 'Contrato'],
        'midia': ['Midia'],
        'amostra': ['Amostra', 'Local_de_Coleta'],
        'financiamento': ['Financiamento', 'Financiador']
    }
    
    # Busca por palavras-chave
    for palavra, tabelas in palavras_chave_tabela.items():
        if palavra in texto:
            tabelas_relevantes.extend(tabelas)
    
    # Busca por nomes exatos de tabelas
    for tabela_nome in schema:
        if tabela_nome.lower() in texto:
            tabelas_relevantes.append(tabela_nome)
    
    # Remove duplicatas e usa todas as tabelas se não encontrar nada
    tabelas_relevantes = list(set(tabelas_relevantes)) if tabelas_relevantes else list(schema.keys())
    
    # Inclui tabelas relacionadas (foreign keys)
    tabelas_com_relacionamentos = set(tabelas_relevantes)
    for tabela in tabelas_relevantes:
        if tabela in schema:
            # Adiciona lógica para incluir tabelas relacionadas baseado no schema
            # Por exemplo, se mencionar 'Especime', incluir 'Especie'
            if tabela == 'Especime':
                tabelas_com_relacionamentos.add('Especie')
            elif tabela == 'Especie':
                tabelas_com_relacionamentos.add('Taxon')
    
    schema_reduzido = {t: schema[t] for t in tabelas_com_relacionamentos if t in schema}
    
    # Monta informação de relacionamentos
    relacionamentos_info = """
    RELACIONAMENTOS PRINCIPAIS:
    - Especie → Taxon (via ID_Gen)
    - Especime → Especie (via ID_Esp)
    - Midia → Especime (via ID_Especime)
    - Amostra → Especie e Local_de_Coleta
    - Projeto relaciona-se com Funcionario, Especie, Categoria
    - Contrato → Funcionario e Laboratorio
    """
    
    campos_str = "\n".join(
        f"- {t}: {', '.join([col['nome'] for col in schema_reduzido[t]])}"
        for t in schema_reduzido
    )

    prompt = f"""
    Você é um assistente SQL especializado em bancos de dados de laboratórios de taxonomia.
    
    SCHEMA DISPONÍVEL:
    {campos_str}
    
    {relacionamentos_info}
    
    PEDIDO DO USUÁRIO: "{user_prompt}"
    
    INSTRUÇÕES:
    - Gere APENAS a query SQL, sem explicações
    - Use JOIN quando necessário para relacionar tabelas
    - Use nomes de colunas exatos do schema
    - Para campos de data, use formato 'YYYY-MM-DD'
    - Limite resultados com LIMIT quando apropriado
    
    QUERY SQL:
    """
    
    resposta = generate_data(prompt, modelo=modelo, temperatura=temperatura)
    
    if resposta:
        # Remove possíveis explicações extras
        linhas = resposta.strip().split('\n')
        for linha in linhas:
            linha_limpa = linha.strip()
            if linha_limpa and not linha_limpa.startswith(('--', '/*', '#')):
                return linha_limpa
    
    return resposta.strip() if resposta else None


def make_query(conexao, sql_query):
    """
    Executa uma consulta SQL na conexão fornecida e exibe os resultados.
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados.
        sql_query (str): Consulta SQL a ser executada.
    """
    cursor = conexao.cursor()
    
    try:
        cursor.execute(sql_query)
        resultados = cursor.fetchall()
        colunas = [desc[0] for desc in cursor.description]

        if resultados:
            print(f"Resultados da query '{sql_query}':")
            for linha in resultados:
                print(dict(zip(colunas, linha)))
        else:
            print("Nenhum resultado encontrado.")
    except mysql.connector.Error as err:
        print(f"Erro ao executar a query: {err}")
    finally:
        cursor.close()


def generate_embeddings(img_bytes):
    """
    Gera um vetor de embedding normalizado para uma imagem fornecida em bytes.
    Parâmetros:
        img_bytes (bytes): Os bytes da imagem a ser processada.
    Retorna:
        np.ndarray ou None: O vetor de embedding normalizado da imagem, ou None em caso de erro.
    """
    
    try:
        imagem = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception as e:
        print(f"Erro ao abrir imagem: {e}")
        return None

    try:
        inputs = clip_processor(images=imagem, return_tensors="pt")
        with torch.no_grad():
            embedding = clip_model.get_image_features(**inputs)
        embedding_np = embedding[0].cpu().numpy()
        # Normaliza o vetor para facilitar comparação de similaridade
        norm = np.linalg.norm(embedding_np)
        if norm == 0:
            return embedding_np
        return embedding_np / norm
    except Exception as e:
        print(f"Erro ao gerar embedding: {e}")
        return None


def search_similarity(conexao, imagem_consulta_bytes, top_k=3):
    """
    Busca as imagens mais similares à imagem de consulta no banco de dados, utilizando embeddings e similaridade de cosseno.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Conexão ativa com o banco de dados.
        imagem_consulta_bytes (bytes): Imagem de consulta em formato de bytes.
        top_k (int, opcional): Número de imagens mais similares a serem retornadas. Padrão é 3.
    Retorna:
        None. Exibe no console as imagens mais similares, suas similaridades e informações da espécie associada.
    """
    
    cursor = conexao.cursor()
    cursor.execute("SELECT ID_Midia, Dado FROM Midia")
    midias = cursor.fetchall()
    cursor.close()

    if not midias:
        print("Nenhuma imagem cadastrada.")
        return

    # Gere embedding da imagem de consulta
    emb_consulta = generate_embeddings(imagem_consulta_bytes)
    
    if emb_consulta is None:
        print("Erro ao gerar embedding da imagem de consulta.")
        return

    # Gere embeddings das imagens do banco
    embeddings = []
    ids = []
    for id_midia, dado in midias:
        try:
            emb = generate_embeddings(dado)
            if emb is not None:
                embeddings.append(emb)
                ids.append(id_midia)
        except (OSError, IOError) as e:
            print(f"Erro ao processar imagem ID {id_midia}: {e}")

    if not embeddings:
        print("Nenhuma imagem válida para comparar.")
        return

    # Calcule similaridade
    sims = cosine_similarity([emb_consulta], embeddings)[0]
    top_idx = np.argsort(sims)[::-1][:top_k]

    print("Imagens mais similares e suas espécies:")
    cursor = conexao.cursor()
    for i in top_idx:
        id_midia = ids[i]
        # Corrigida a consulta SQL baseada no schema real
        cursor.execute("""
            SELECT e.Nome, e.Descricao
            FROM Midia m
            JOIN Especime es ON m.ID_Especime = es.ID_Especime
            JOIN Especie e ON es.ID_Esp = e.ID_Esp
            WHERE m.ID_Midia = %s
            LIMIT 1
        """, (id_midia,))
        especie = cursor.fetchone()
        if especie:
            nome, descricao = especie
        else:
            nome, descricao = "Espécie não encontrada", "-"
        print(f"ID_Midia: {id_midia}, Similaridade: {sims[i]:.3f}, Espécie: {nome}, Descrição: {descricao}")
    cursor.close()


def exit_db(conexao):
    """
    Encerra a conexão com o banco de dados.
    Parâmetros:
        conexao (mysql.connector.connection.MySQLConnection): Objeto de conexão com o banco de dados.
    Exceções:
        mysql.connector.Error: Caso ocorra um erro ao tentar encerrar a conexão.
    """
    
    try:
        if conexao.is_connected():
            conexao.close()
            print("Conexão com o banco de dados foi encerrada!")
        else:
            print("A conexão já estava encerrada.")
    except mysql.connector.Error as err:
        print(f"Erro ao encerrar a conexão: {err}")


def crud(conexao):
    # Exemplo de CRUD completo usando as funções já implementadas
    
    # 1. Deletar todas as tabelas (limpa o banco)
    print("\n[CRUD] Deletando todas as tabelas...")
    drop_tables(conexao)

    # 2. Criar todas as tabelas a partir do arquivo script.sql
    print("\n[CRUD] Criando tabelas a partir de 'script.sql'...")
    create_tables(conexao)

    # 3. Popular todas as tabelas automaticamente com dados gerados por IA
    print("\n[CRUD] Populando tabelas automaticamente...")
    populate_all_tables(conexao, n_linhas=10)

    # 4. Mostrar dados de todas as tabelas
    print("\n[CRUD] Exibindo dados de todas as tabelas:")
    schema = get_schema_info(conexao)
    for tabela_nome in schema:
        print(f"\n--- {tabela_nome.upper()} ---")
        cursor = conexao.cursor()
        cursor.execute(f"SELECT * FROM `{tabela_nome}`")
        linhas = cursor.fetchall()
        for linha in linhas:
            print(linha)
        cursor.close()

    
    if schema:
        # 5. Atualizar algumas linhas aleatórias de uma tabela
        tabela_exemplo = next(iter(schema))
        print(f"\n[CRUD] Atualizando 3 linhas aleatórias da tabela '{tabela_exemplo}'...")
        update_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=3)

        # 6. Deletar algumas linhas aleatórias da mesma tabela
        print(f"\n[CRUD] Deletando 2 linhas aleatórias da tabela '{tabela_exemplo}'...")
        delete_random_rows(conexao, tabela_nome=tabela_exemplo, n_linhas=2)

    print("\n[CRUD] CRUD automatizado finalizado.")


if __name__ == "__main__":
    try:
        con = connect_mysql(host="localhost", user="root", password="mysql", database="trabalho_final")

        if not con:
            print("Não foi possível conectar ao banco de dados.")
            exit(1)

        while True:
            print("""
                ╔═════════════════════════════════════════════╗
                ║             NEXUS-BIO CMD v1.4              ║
                ║---------------------------------------------║
                ║ [  1 ] > Criar Tabelas                      ║
                ║ [  2 ] > Apagar Tabelas                     ║
                ║ [  3 ] > Visualizar Tabelas                 ║
                ║ [  4 ] > Inserir Dados Manualmente          ║
                ║ [  5 ] > Atualizar Dados Manualmente        ║
                ║ [  6 ] > Deletar Dados Manualmente          ║
                ║ [  7 ] > IA: Preencher Tabelas              ║
                ║ [  8 ] > IA: Atualizar Dados Aleatórios     ║
                ║ [  9 ] > IA: Gerar SQL a partir de Texto    ║
                ║ [ 10 ] > IA: Buscar Imagens Similares       ║
                ║ [ 11 ] > Executar CRUD Automático           ║
                ║ [ 12 ] > Remover Dados Aleatórios           ║
                ║ [  0 ] > Explodir Sistema                   ║
                ╚═════════════════════════════════════════════╝
            """)

            try:
                opcao = int(input("Opção: ").strip())
                if opcao < 0 or opcao > 12:
                    print("Opção inválida. Escolha um número entre 0 e 12.")
                    continue
            except ValueError:
                print("Entrada inválida. Por favor, digite um número.")
                continue

            match opcao:
                case 0:
                    exit_db(con)
                    print("Saindo do NEXUS-BIO CMD...")
                    print("Preparando explosivos...")
                    break

                case 1:
                    create_tables(con)

                case 2:
                    drop_tables(con)
                    
                case 3:
                    show_tables(con)

                case 4:
                    insert_by_user(con)

                case 5:
                    update_by_user(con)

                case 6:
                    delete_by_user(con)

                case 7:
                    n = input("Quantas linhas por tabela? [padrão=10]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 10
                    populate_all_tables(con, n_linhas=n)

                case 8:
                    tabela = input("Tabela para atualizar: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    update_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case 9:
                    prompt_usuario = input("Digite sua consulta em linguagem natural: ").strip()
                    if prompt_usuario:
                        db_schema = get_schema_info(con)
                        query = generate_sql_query(prompt_usuario, db_schema)
                        print(f"Query gerada: {query}")
                        make_query(con, query)
                
                case 10:
                    caminho_imagem = input("Caminho da imagem para busca: ").strip()
                    try:
                        with open(caminho_imagem, "rb") as f:
                            imagem_bytes = f.read()
                        search_similarity(con, imagem_consulta_bytes=imagem_bytes)
                    except FileNotFoundError:
                        print(f"Arquivo '{caminho_imagem}' não encontrado.")
                    except OSError as e:
                        print(f"Erro ao processar a imagem: {e}")
                
                case 11:
                    print("\nIniciando CRUD Automático...")
                    crud(con)
                    
                case 12:
                    tabela = input("Tabela para deletar linhas: ").strip()
                    n = input("Quantas linhas aleatórias? [padrão=5]: ").strip()
                    n = int(n) if n.isdigit() and int(n) > 0 else 5
                    delete_random_rows(con, tabela_nome=tabela, n_linhas=n)

                case _:
                    print("Opção inválida. Tente novamente.")

    except mysql.connector.Error as err:
        print("Erro na conexão com o banco de dados!", err)
    except KeyboardInterrupt:
        print("\n\nPrograma interrompido pelo usuário.")
    except FileNotFoundError as fnf_err:
        print(f"Erro de arquivo não encontrado: {fnf_err}")
    except ValueError as val_err:
        print(f"Erro de valor: {val_err}")
    except OSError as os_err:
        print(f"Erro do sistema operacional: {os_err}")
    except (RuntimeError, AttributeError, TypeError) as e:
            print(f"Erro inesperado: {e}")
    finally:
            if 'con' in locals() and con.is_connected():
                exit_db(con)