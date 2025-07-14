## Introduzione

Questo repository contiene uno script Python progettato per monitorare la presenza di beacon Bluetooth e aggiornare lo stato di bambini associati in un database Firestore. È ideale per applicazioni come il monitoraggio della presenza di bambini su uno scuolabus o in ambienti specifici, garantendo che lo stato di "a bordo" o "assente" sia sempre aggiornato in tempo reale. Nell’ottica di un’automazione completa e per minimizzare l’intervento umano, il sistema è stato progettato per essere pienamente compatibile con un meccanismo di rilevamento automatico della presenza basato su tecnologie Bluetooth Low Energy (BLE) e l’impiego di un Raspberry Pi a bordo del veicolo. L’idea concettuale prevede che ogni bambino sia dotato di un piccolo beacon BLE. Un modulo Raspberry Pi, installato sullo scuolabus, agirebbe come “ scanner”, rilevando la presenza dei beacon (e quindi dei bambini) nelle vicinanze. Al momento della salita o della discesa, il Raspberry Pi sarebbe in grado di identificare l’ingresso o l’uscita del beacon dell’area di rilevamento e, di conseguenza, di aggiornare automaticamente lo stato di presenza del bambino nel database Cloud Firestore. Questo approccio eliminerebbe la necessità di controlli manuali, riducendo gli errori e accelerando la disponibilità delle informazioni.

## Architettura del Sistema

L'architettura del sistema B.U.S. si compone di un dispositivo edge (Raspberry Pi), un backend serverless su Firebase (Cloud Functions, Firestore, Authentication) e un'applicazione frontend (Angular) per la gestione e la visualizzazione dei dati. 

## Dettagli del componente edge

Questo componente è implementato su un Raspberry Pi e include uno script Python (codice_presenze.py) che agisce come un "edge device" per il progetto
Il dispositivo esegue i seguenti compiti:
- Rilevamento dei Beacon: Scansiona continuamente l'ambiente circostante per rilevare la presenza di specifici beacon Bluetooth Low Energy (BLE) registrati nel database.
- Monitoraggio dello Stato in Tempo Reale: Mantiene una traccia dello stato di presenza (a bordo o assente) per ogni bambino, aggiornando il suo stato solo quando un cambiamento viene rilevato. Questo riduce il traffico dati verso il cloud.
- Sincronizzazione con Firestore: Quando lo stato di un bambino cambia, lo script invia un aggiornamento mirato a Firestore. Questo aggiornamento modifica il campo statoPresenza e imposta un ultimaAttivita con il timestamp del server per fornire una traccia temporale precisa dell'evento.