from bluepy.btle import Scanner, BTLEDisconnectError
import time
from datetime import datetime
import pytz # Per gestire i fusi orari
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions # Importa le eccezioni di Firebase
from google.cloud.firestore_v1.base_query import FieldFilter

# --- Configurazione Firebase ---
SERVICE_ACCOUNT_KEY_PATH = '/home/prima-bisanti/iot-scuoabus-firebase-adminsdk-fbsvc-2e41630be1.json'

try:
    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Connesso a Firebase Firestore!")
except Exception as e:
    print(f"Errore durante l'inizializzazione di Firebase: {e}")
    print("Assicurati che il percorso alla chiave dell'account di servizio sia corretto.")
    exit(1)

# --- Configurazione Beacon Scanner ---
# DURATION_SCAN_SECONDS: Durata di ogni ciclo di scansione Bluetooth.
# SCAN_INTERVAL_SECONDS: Tempo di pausa tra la fine di una scansione e l'inizio della successiva.
# PRESENCE_TIMEOUT_SECONDS: Tempo (in secondi) entro cui un beacon è considerato presente dall'ultima rilevazione.
#                           Se un beacon non viene rilevato per questo intervallo, il suo stato passa a "assente".
DURATION_SCAN_SECONDS = 5
SCAN_INTERVAL_SECONDS = 10
PRESENCE_TIMEOUT_SECONDS = 20

# --- Stato del monitoraggio (in memoria sul Raspberry) ---
# Contiene i dati dei beacon da monitorare, caricati da Firestore.
# Formato: { 'MAC_ADDRESS': { 'id': 'doc_id_beacon', 'nomeBeacon': 'BeaconX', 'assignedChildId': 'child_doc_id' } }
MONITORED_BEACONS = {}

# Salva l'ultimo timestamp UNIX di rilevazione per ogni MAC address noto.
# Formato: { 'MAC_ADDRESS': UNIX_TIMESTAMP_ULTIMO_RILEVAMENTO }
last_seen_timestamp = {}

# Stato corrente di presenza per ogni beacon (in memoria).
# Formato: { 'MAC_ADDRESS': 'a bordo' | 'assente' } (corrisponde ai valori di Firestore)
current_beacon_states = {}

# Mappa lo stato interno a quello di Firestore per il bambino
STATUS_MAPPING = {
    "A bordo": "A bordo",
    "Sceso": "Sceso"
}
REVERSE_STATUS_MAPPING = { # Utile per il logging
    "A bordo": "A bordo",
    "Sceso": "Sceso"
}

def load_beacons_from_firestore():
    """
    Carica i beacon dalla collezione 'beacon' di Firestore.
    Popola MONITORED_BEACONS, last_seen_timestamp e current_beacon_states.
    """
    global MONITORED_BEACONS, last_seen_timestamp, current_beacon_states
    beacons_ref = db.collection('beacon')
    try:
        # Filtra solo beacon che sono stati assegnati e che hanno un assignedChildId
        docs = beacons_ref.where(filter = FieldFilter('isAssegnato', '==', True)).stream() 
        temp_monitored_beacons = {}
        for doc in docs:
            beacon_data = doc.to_dict()
            beacon_doc_id = doc.id # ID del documento beacon in Firestore

            if ('indirizzoMac' in beacon_data and
                'nomeBeacon' in beacon_data and
                'assignedChildId' in beacon_data and
                beacon_data['assignedChildId']):

                mac_address = beacon_data['indirizzoMac']
                temp_monitored_beacons[mac_address] = {
                    'id': beacon_doc_id, # L'ID del documento beacon
                    'nomeBeacon': beacon_data['nomeBeacon'],
                    'assignedChildId': beacon_data['assignedChildId']
                }
            else:
                print(f"ATTENZIONE: Documento beacon {doc.id} non valido (campi essenziali mancanti o beacon non assegnato correttamente).")
        
        # Aggiorna le variabili globali solo dopo aver completato il caricamento
        MONITORED_BEACONS = temp_monitored_beacons
        
        # Inizializza gli stati interni e i timestamp.
        # Tutti i beacon iniziano come "assente" (Sceso) e non rilevati.
        for mac in MONITORED_BEACONS:
            last_seen_timestamp[mac] = 0
            current_beacon_states[mac] = STATUS_MAPPING["Sceso"] 

        print(f"Caricati {len(MONITORED_BEACONS)} beacon assegnati da Firestore.")
        if not MONITORED_BEACONS:
            print("Nessun beacon assegnato trovato. Lo scanner sarà inattivo finché non verranno assegnati beacon.")

    except firebase_exceptions.FirebaseError as e:
        print(f"Errore di Firebase durante il caricamento dei beacon: {e}")
    except Exception as e:
        print(f"Errore generico durante il caricamento dei beacon da Firestore: {e}")
    
def scan_and_update_db():
    """Esegue la scansione dei beacon e aggiorna lo stato dei figli su Firestore."""
    
    # Se non ci sono beacon monitorati, prova a caricarli di nuovo
    if not MONITORED_BEACONS:
        print("Nessun beacon caricato. Riprovo a caricarli da Firestore...")
        load_beacons_from_firestore()
        if not MONITORED_BEACONS:
            print("Ancora nessun beacon da monitorare. Attendo...")
            return # Nessun beacon, non fare la scansione

    scanner = Scanner()
    current_unix_time = time.time() # Timestamp UNIX corrente

    print("_________________________________________")
    print(f"Inizio scansione Bluetooth ({datetime.now(pytz.timezone('Europe/Rome')).strftime('%Y-%m-%d %H:%M:%S')})...")

    try:
        # La scansione dura DURATION_SCAN_SECONDS secondi
        devices = scanner.scan(DURATION_SCAN_SECONDS)
    except BTLEDisconnectError as e:
        print(f"Errore Bluetooth: {e}. Assicurati che l'adattatore Bluetooth sia attivo. Riprovo...")
        return # Esci e riprova al prossimo ciclo
    except Exception as e:
        print(f"Errore generico durante la scansione: {e}")
        return

    # Aggiorna il timestamp dell'ultimo rilevamento per i beacon visti in questa scansione
    for dev in devices:
        if dev.addr in MONITORED_BEACONS:
            last_seen_timestamp[dev.addr] = current_unix_time

    # Verifica lo stato di presenza e aggiorna Firestore se necessario
    for mac_address, beacon_info in MONITORED_BEACONS.items():
        child_doc_id = beacon_info['assignedChildId']
        nome_beacon = beacon_info['nomeBeacon']
        
        # Determina lo stato attuale in base all'ultimo rilevamento
        is_present_now = (current_unix_time - last_seen_timestamp.get(mac_address, 0)) <= PRESENCE_TIMEOUT_SECONDS
        
        # Mappa lo stato booleano a stringa per Firestore: 'A bordo' o 'Sceso'
        new_status_firestore = STATUS_MAPPING["A bordo"] if is_present_now else STATUS_MAPPING["Sceso"]

        # Recupera lo stato precedente memorizzato localmente
        previous_status_local = current_beacon_states.get(mac_address)

        # Se lo stato è cambiato o è il primo avvio e lo stato è diverso da quello di default 'Sceso'
        if new_status_firestore != previous_status_local:
            current_beacon_states[mac_address] = new_status_firestore # Aggiorna lo stato in memoria

            try:
                # Ottieni il riferimento al documento del bambino
                child_doc_ref = db.collection('figli').document(child_doc_id)
                
                # Aggiorna il campo statoPresenza del bambino in Firestore
                child_doc_ref.update({
                    "statoPresenza": new_status_firestore,
                    "ultimaAttivita": firestore.SERVER_TIMESTAMP # Utilizza il timestamp del server Firestore
                })
                
                # Logga il cambio di stato con il fuso orario italiano
                timestamp_locale = datetime.now(pytz.timezone("Europe/Rome"))
                print(f"[CAMBIO STATO FIRESTORE] {timestamp_locale.strftime('%Y-%m-%d %H:%M:%S')} | "
                      f"Beacon: {nome_beacon} ({mac_address}) | "
                      f"Bambino ID: {child_doc_id} | "
                      f"Nuovo Stato: {REVERSE_STATUS_MAPPING[new_status_firestore]}")

            except firebase_exceptions.NotFound:
                print(f"AVVISO: Bambino con ID '{child_doc_id}' non trovato in Firestore per il beacon {nome_beacon} ({mac_address}).")
            except firebase_exceptions.FirebaseError as e:
                print(f"ERRORE FIRESTORE: Impossibile aggiornare lo stato del bambino {child_doc_id} ({nome_beacon}): {e}")
            except Exception as e:
                print(f"ERRORE GENERICO: Durante l'aggiornamento dello stato del bambino {child_doc_id} ({nome_beacon}): {e}")
        else:
            pass

    print("--- Scansione completata ---")

# --- Avvio del monitoraggio ---
print("Avvio monitoraggio beacon... (Ctrl+C per uscire)")
try:
    load_beacons_from_firestore() # Carica i beacon all'avvio
    while True:
        scan_and_update_db()
        time.sleep(SCAN_INTERVAL_SECONDS) # Pausa tra un ciclo di scansione e il successivo
except KeyboardInterrupt:
    print("Monitoraggio interrotto dall'utente.")
finally:
    print("Monitoraggio terminato.")
