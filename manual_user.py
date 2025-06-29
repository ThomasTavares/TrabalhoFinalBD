from db_operations import print_tables, show_table, insert_data
import mysql.connector

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
    
    check_check(conexao, tabela_nome)
    
    # Exibe valores já registrados na tabela
    print("\nValores registrados:")
    show_table(conexao, tabela_nome)

    # Coleta valores para cada campo
    print("\nPreencha os valores para cada campo (digite 'null' para deixar campo vazio):")
    valores = []
    for campo in colunas:
        # Busca informações do campo
        campo_info = next((col for col in colunas_detalhadas if col[0] == campo), None)
        tipo_campo = (campo_info[1] if campo_info else "unknown").lower()
        
        # Solicita valor do usuário
        valor = check_type(campo, tipo_campo)
        
        # Insere o valor na lista
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
        print(f"Inserção falhou: {e}")
    finally:
        cursor.close()
    print("\n" + "="*50)


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
    
    if num_linhas == 0:
        cursor.close()
        return

    campo = input("\nCampo a atualizar: ").strip()
    
    print("\n")
    check_check(conexao, tabela_nome, campo)
    
    cursor.execute(f"DESCRIBE `{tabela_nome}`")
    colunas_detalhadas = cursor.fetchall()
    campo_info = next((col for col in colunas_detalhadas if col[0] == campo), None)
    tipo_campo = (campo_info[1] if campo_info else "unknown").lower()
    cursor.close()
    
    print("\nNovo valor:")
    valor = check_type(campo, tipo_campo)
    condicao = input("\nInsira a condição WHERE (ex: id =  1): ").strip()

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


def format_check(resultado, campo=None):
    '''Formata e exibe os valores permitidos de uma CHECK constraint.
    Parâmetros:
        resultado: Resultado da consulta de CHECK constraints.
        campo: (opcional) Nome do campo específico para filtrar os resultados.
    Retorna:
        None.
    '''
    check = resultado[1] if isinstance(resultado, tuple) else resultado
    match = re.search(r"`(\w+)`\s+in\s*\((.*?)\)", check, re.IGNORECASE)
    
    if match:
        if campo and campo.lower() != match.group(1).lower():
            return
        
        atributo = match.group(1)
        valores = match.group(2)
        
        valores_formatados = re.findall(r"'([^']+)'", valores)
        print(f"\nValores permitidos para '{atributo}': {', '.join(valores_formatados)}")


def check_check(conexao, tabela, campo=None):
    '''
    Verifica se a tabela possui CHECK constraints
    Parâmetros:
        conexao: Objeto de conexão com o banco de dados MySQL.
        tabela: Nome da tabela a ser verificada.
        campo: (opcional) Nome do campo específico para filtrar os resultados.
    Retorna:
        None.
    '''
    cursor = conexao.cursor()
    cursor.execute("SET NAMES utf8mb4;")
    
    cursor.execute(f"SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE FROM information_schema.check_constraints cc JOIN information_schema.table_constraints tc ON cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME WHERE tc.TABLE_NAME = '{tabela}' AND tc.TABLE_SCHEMA = 'trabalho_final' AND tc.CONSTRAINT_TYPE = 'CHECK';")
    resultados = cursor.fetchall()
    
    if campo:
        for resultado in resultados:
            format_check(resultado, campo)
    else:
        for resultado in resultados:
            format_check(resultado)
                
    cursor.close()


def check_type(campo, tipo_campo):
    """
    Verifica se o valor de entrada é compatível com o tipo do campo.
    Parâmetros:
        tipo_campo (str): Tipo do campo.
    Retorna:
        valor (int, float, str, None): Valor convertido para o tipo correto ou None se inválido.
    """
    if 'timestamp' in tipo_campo:
        valor = (datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        print(f"• {campo} ({tipo_campo}): {valor} [AUTO-GERADO]")
    elif 'blob' in tipo_campo:
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
        elif 'int' in tipo_campo:
            try:
                valor = int(valor_input)
            except ValueError:
                print(f"Valor inválido para {campo}. Usando 0.")
                valor = 0
        elif 'decimal' in tipo_campo or 'float' in tipo_campo:
            try:
                valor = float(valor_input)
            except ValueError:
                print(f"Valor inválido para {campo}. Usando 0.0.")
                valor = 0.0
        elif 'date' in tipo_campo:
            # Verifica se a data está no formato YYYY-MM-DD
            if re.match(r'^\d{4}-\d{2}-\d{2}$', valor_input):
                valor = valor_input
            else:
                print(f"Formato de data inválido para {campo}. Usando data atual.")
                valor = (datetime.now()).strftime('%Y-%m-%d')
        elif 'varchar' in tipo_campo:
            # Extrai o tamanho máximo do varchar
            match = re.search(r'varchar\((\d+)\)', tipo_campo)
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
    
    return valor
