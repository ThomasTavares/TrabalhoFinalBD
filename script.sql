CREATE TABLE Taxon (
	ID_Tax integer PRIMARY KEY,
	Tipo varchar(10) NOT NULL,
	Nome varchar(50) NOT NULL,
	UNIQUE (Tipo, Nome),
	CHECK (Tipo IN ('Dominio', 'Reino', 'Filo', 'Classe', 'Ordem', 'Familia', 'Genero')));

CREATE TABLE Hierarquia (
	ID_Tax integer PRIMARY KEY,
	ID_TaxTopo integer NOT NULL,
	FOREIGN KEY(ID_Tax) REFERENCES Taxon (ID_Tax),
	FOREIGN KEY(ID_TaxTopo) REFERENCES Taxon (ID_Tax));

CREATE TABLE Especie (
	ID_Esp integer PRIMARY KEY,
	ID_Gen integer NOT NULL,
	Nome varchar(50) NOT NULL,
	Nome_Pop varchar(50),
	Descricao varchar(500),
	IUCN varchar(2),
	FOREIGN KEY(ID_Gen) REFERENCES Taxon (ID_Tax),
	CHECK (IUCN IN ('LC', 'NT', 'VU', 'EN', 'CR', 'EW', 'EX')));

CREATE TABLE Especime (
	ID_Especime integer PRIMARY KEY,
	ID_Esp integer NOT NULL,
	Descritivo varchar(50),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Local_de_Coleta (
	ID_Local integer PRIMARY KEY,
	Nome varchar(50) NOT NULL,
	Endereco varchar(100) NOT NULL);

CREATE TABLE Amostra (
	ID_Amos integer PRIMARY KEY,
	ID_Esp integer NOT NULL,
	ID_Local integer NOT NULL,
	Tipo varchar(50) NOT NULL,
	Dt_Coleta date NOT NULL,
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp),
	FOREIGN KEY(ID_Local) REFERENCES Local_de_Coleta (ID_Local));

CREATE TABLE Midia (
	ID_Midia integer PRIMARY KEY AUTO_INCREMENT,
	ID_Especime integer NOT NULL,
	Tipo varchar(50) NOT NULL,
	Dado blob,	-- BLOB = Binary Large Object
	FOREIGN KEY(ID_Especime) REFERENCES Especime (ID_Especime));

CREATE TABLE Projeto (
	ID_Proj integer PRIMARY KEY,
	Nome varchar(50) NOT NULL,
	Descricao varchar(100) NOT NULL,
	Status varchar(50) NOT NULL,
	Dt_Inicio date,
	Dt_Fim date,
	CHECK (Status IN ('Planejado', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado')));
    
CREATE TABLE Artigo (
	ID_Artigo integer PRIMARY KEY,
	ID_Proj integer NOT NULL,
	Titulo varchar(50) NOT NULL,
	Resumo varchar(2500) NOT NULL,
	DOI varchar(50) NOT NULL,
	Link varchar(100),
	Dt_Pub date NOT NULL,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj));

CREATE TABLE Funcionario (
	ID_Func integer PRIMARY KEY,
	Nome varchar(50) NOT NULL,
	CPF varchar(11) NOT NULL,
	Cargo varchar(50) NOT NULL,
	UNIQUE (CPF));
    
CREATE TABLE Proj_Func (
	ID_Proj integer,
	ID_Func integer,
	PRIMARY KEY(ID_Proj, ID_Func),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func));
    
CREATE TABLE Proj_Esp (
	ID_Proj integer,
	ID_Esp integer,
	PRIMARY KEY(ID_Proj,ID_Esp),
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Esp) REFERENCES Especie (ID_Esp));

CREATE TABLE Categoria (
	ID_Categ integer PRIMARY KEY,
	Descritivo varchar(50) NOT NULL);

CREATE TABLE Proj_Cat (
	ID_Proj integer,
	ID_Categ integer,
	PRIMARY KEY(ID_Proj,ID_Categ),
	FOREIGN KEY(ID_Categ) REFERENCES Categoria (ID_Categ));

CREATE TABLE Laboratorio (
	ID_Lab integer PRIMARY KEY,
	Nome varchar(50) NOT NULL,
	Endereco varchar(100) NOT NULL);

CREATE TABLE Contrato (
	ID_Contrato integer PRIMARY KEY,
	ID_Func integer NOT NULL,
	ID_Lab integer NOT NULL,
	Status varchar(50) NOT NULL,
	Dt_Inicio date,
	Dt_Fim date,
	Valor decimal(10,2) NOT NULL,
	CHECK (Status IN ('Pendente', 'Ativo', 'Suspenso', 'Cancelado', 'Encerrado')),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Financiador (
	ID_Financiador integer PRIMARY KEY,
	Descritivo varchar(50) NOT NULL,
	Endereco varchar(100) NOT NULL);

CREATE TABLE Financiamento (
	ID_Financiamento integer PRIMARY KEY,
	ID_Proj integer NOT NULL,
	ID_Financiador integer NOT NULL,
	Valor decimal(10,2) NOT NULL,
	Dt_Financ date NOT NULL,
	FOREIGN KEY(ID_Proj) REFERENCES Projeto (ID_Proj),
	FOREIGN KEY(ID_Financiador) REFERENCES Financiador (ID_Financiador));

CREATE TABLE Equipamento (
	ID_Equip integer PRIMARY KEY,
	ID_Lab integer NOT NULL,
	Tipo varchar(50) NOT NULL,
	Modelo varchar(50) NOT NULL,
	FOREIGN KEY(ID_Lab) REFERENCES Laboratorio (ID_Lab));

CREATE TABLE Registro_de_Uso (
	ID_Func integer,
	ID_Equip integer,
	Dt_Reg timestamp NOT NULL,
	PRIMARY KEY(ID_Func,ID_Equip),
	FOREIGN KEY(ID_Func) REFERENCES Funcionario (ID_Func),
	FOREIGN KEY(ID_Equip) REFERENCES Equipamento (ID_Equip));