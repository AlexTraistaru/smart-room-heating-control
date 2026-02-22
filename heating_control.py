# a - mod automat
# m - mod manual
# p <0..100> - seteaza puterea in mod manual
# q - oprim . stop_event se seteaza si task ul se termina

# T (achizitie temperatura) produce periodic TC1...TCn si trimite catre S
# S (decizie) calculeaza confortul si:
#       in modul automat, calculeaza puterea si o transmite catre P
#       in modul manual, nu calculeaza puterea; foloseste puterea data de SW (si doar afiseaza)
# P mentine presiunea in limite, folosind puterea curenta
# SW (interfata) selecteaza modul si (in manual) stabileste puterea

# queue - cozi pentru comunicare intre thread-uri (mesaje)
# random - punem un zgomot mic in temperatura/presiune ca sa fie mai realist
# threading -thread-uri + Lock (mutex) + Event (semnal de oprire)
# cand un ask ia lock ul doar el poate citi/scrie in zona partajata. celelalte thread-uri asteapta, se previne race condition
# stop_event - semnal de oprire pentru toate thread-urile. E ca un steag, cat timp nu e setat, thread-urile ruleaza, dupa ce e setat se opresc
# time - time.monotonic(), este un ceas care nu se da inapoi (nu e afectat de schimbari de ora sistem), pentru perioade stabile de timp (ex: fac ceva la fiecare 0.5 secunde)
import queue
import random
import threading
import time

def limiteaza(valoare, minim, maxim):
    # intoarce valoarea in intervalul [minim, maxim]
    # ex: calculez puterea si da 110%, o limitez la 100%
    # ex: utilizatorul incearca sa seteze -20%, o limitez la 0%
    # ex: puterea trebuie sa fie intre 0 si 100.
    if valoare < minim:
        return minim
    if valoare > maxim:
        return maxim
    return valoare

def ultimul_mesaj(coada, mesaj):
    # S trebuie sa lucreze pe date recente, nu pe o lista de date vechi care s-au acumulat.
    # coada are maxsize=1
    # daca e plina, aruncam mesajul vechi
    # punem mesajul nou
    try:
        if coada.full():
            coada.get_nowait() # daca coada e plina, scoatem vechiul mesaj
    except queue.Empty: # daca coada s-a golit intre timp, un alt thread a scos mesajul
        pass

    try:
        coada.put_nowait(mesaj) # incercam sa punem mesajul nou
    except queue.Full:
        # in acel moment coada s-a umplut din nou, renuntam (alt thread a pus ceva intre timp)
        pass

def goleste_coada(coada):
    # Scoate toate elementele ramase in coada, fara sa blocheze thread-ul
    # Folositor la comutare de mod: vrem sa aruncam comenzi vechi
    while True:
        try:
            coada.get_nowait()
        except queue.Empty:
            break


def asteapta_pana_la_urmatoarea_activare(next_release, stop_event):
    # temporizarea corecta pentru un task periodic
    # thread-ul intra in asteptare si nu consuma CPU inutil
    # se trezeste fie la timeout (cand a venit timpul urmator), fie daca stop_event se seteaza
    acum = time.monotonic()
    timp_ramas = next_release - acum
    if timp_ramas > 0:
        stop_event.wait(timeout=timp_ramas)


def calcul_confort(t_medie, t_ref, banda):
    # Decide daca este "rece", "confortabil" sau "cald" fata de temperatura de referinta
    if t_medie < (t_ref - banda):
        return "rece"
    if t_medie > (t_ref + banda):
        return "cald"
    return "confortabil"


def calcul_putere_mod_automat(t_medie, t_ref):
    # Daca temperatura medie este < decat temperatura de referinta - vrem putere mai mare
    # Daca temperatura medie este > decat temperatura de referinta - vrem putere mai mica
    # k = cat de rapid reactioneaza controlul
    k = 12.0
    putere_baza = 30.0  # puterea de baza (cu ea pornim, ajustam dupa)

    eroare = t_ref - t_medie  # daca eroare > 0 - e prea rece
    putere = k * eroare + putere_baza
    return putere

def task_sw(q_evenimente_sw, stop_event, lock_consola):
    # task SW citeste de la tastatura si trimite "evenimente" catre S.
    # interfata cu utilizatorul
    # input() este blocant, dar nu e busy-wait (nu consuma CPU in bucla)
    # blocant adica programul se opreste aici pana se intampla ceva (utilizatorul apasa Enter in cazul nostru)
    # nu tinem lock-ul pe durata input() fiindca altfel S nu mai poate afisa.
    # lock_consola il folosim doar ca sa nu se amestece print-urile intre ele (S si SW pot afisa in acelasi timp si se amesteca liniile)

    with lock_consola:
        print("\n[SW] Introdu comenzi: a / m / p <0..100> / q\n")

    while not stop_event.is_set(): #atata timp cat nu e setat semnalul de oprire
        try:
            linie = input("[SW] > ").strip()
        except (EOFError, KeyboardInterrupt):
            linie = "q"

        if not linie:
            continue

        # Comanda "a" - automat
        if linie.lower() == "a":
            ultimul_mesaj(q_evenimente_sw, {"tip": "set_mod", "mod": "automat"})
            continue

        # Comanda "m" - manual
        if linie.lower() == "m":
            ultimul_mesaj(q_evenimente_sw, {"tip": "set_mod", "mod": "manual"})
            continue

        # Comanda "p ..." - setare putere manuala
        if linie.lower().startswith("p"):
            parti = linie.split()
            if len(parti) != 2:
                with lock_consola:
                    print("[SW] Format corect: p <0..100>")
                continue

            try:
                putere = float(parti[1])
            except ValueError:
                with lock_consola:
                    print("[SW] Valoare invalida. Exemplu: p 80")
                continue

            putere = limiteaza(putere, 0.0, 100.0)
            ultimul_mesaj(q_evenimente_sw, {"tip": "set_putere_manual", "putere": putere})
            continue

        # Comanda "q" - oprire
        if linie.lower() == "q":
            ultimul_mesaj(q_evenimente_sw, {"tip": "oprire"})
            stop_event.set()
            break

        with lock_consola:
            print("[SW] Comanda necunoscuta. Foloseste: a / m / p <0..100> / q")

def task_t(configurare, stare, lock_stare, q_temperaturi, stop_event):
    # task T este un task periodic, la fiecare perioada_T secunde genereaza TC1...TCn si trimite rezultatul catre S prin q_temperaturi
    # parametrii sunt stabiliti in "configurare" in main(), pentru usurinta si testare
    
    # ambient - temperatura din cladire daca nu ar exista incalzirea
    # delta_max - cat se poate urca peste ambient la putere de 100%
    # alpha - cat de repede se apropie temperatura de baza de tinta
    # temperatura_tinta = ambient + delta_max*(putere/100)
    # temperatura_baza se apropie gradual de temperatura_tinta

    ambient = configurare["temperatura_ambient"]        # avem 18 greade C fara incalzire
    delta_max = configurare["delta_max_incalzire"]      # +10C la 100%
    alpha = configurare["viteza_raspuns_temperatura"]   # 0.08 (mai mare = mai rapid)

    temperatura_baza = ambient

    next_release = time.monotonic()

    while not stop_event.is_set():
        next_release += configurare["perioada_T"]

        # Citim puterea curenta sub mutex, ca sa fie consistenta
        with lock_stare:
            putere_curenta = stare["putere_curenta"]

        temperatura_tinta = ambient + delta_max * (putere_curenta / 100.0)
        temperatura_baza = temperatura_baza + alpha * (temperatura_tinta - temperatura_baza)

        temperaturi = []
        for _ in range(configurare["numar_TC"]):
            zgomot = random.uniform(-0.15, 0.15)
            # adaugam zgomot la fiecare termocuplu, senzorii reali nu sunt perfect identici
            # temperatura finala = temperatura_baza + zgomot
            # alegem un numar aleator intre -0.15 si +0.15, uniform adica toate valorile din interval au sanse egale
            temperaturi.append(temperatura_baza + zgomot)

        # mesajul catre S: dict (dictionar) cu timp + lista temperaturi
        mesaj = {"timestamp": time.monotonic(), "temperaturi": temperaturi}

        # pastram doar ultimul mesaj (latest only)
        ultimul_mesaj(q_temperaturi, mesaj)

        # asteptare periodica fara busy-wait
        asteapta_pana_la_urmatoarea_activare(next_release, stop_event)

def task_p(configurare, stare, lock_stare, q_comenzi_automat, q_presiune, stop_event):
    # ruleaza periodic (perioada_P)
    # citeste presiunea si decide actiunea asupra valvei
    # trebuie sa foloseasca puterea corecta in functie de mod:
    #     in modul automat, puterea vine de la S prin q_comenzi_automat
    #     in modul manual, puterea vine direct din stare (setata de SW)
    
    # previne o secventa gresita de funcionare:
    # daca SW trece pe manual, in coada pot ramane comenzi automate vechi, P trebuie sa ignore acele comenzi vechi: 
    # cand detectam mod="manual", golim coada q_comenzi_automat

    presiune = configurare["presiune_referinta"]
    actiune_valva = 0.0

    mod_anterioar = None  # ca sa detectam schimbare de mod

    next_release = time.monotonic()

    while not stop_event.is_set():
        next_release += configurare["perioada_P"]

        # Citim modul si puterea curenta din zona partajata, folosita de mai multe task uri (sub mutex)
        with lock_stare:
            mod_curent = stare["mod"]
            putere_curenta = stare["putere_curenta"]

        # Daca tocmai am intrat in manual, aruncam comenzile automate ramase
        if mod_curent == "manual" and mod_anterioar != "manual":
            goleste_coada(q_comenzi_automat)

        mod_anterioar = mod_curent

        # Daca suntem in modul automat, incercam sa luam ultima comanda automata de la S
        # get_nowait() = neblocant: daca nu exista mesaj, arunca exceptie imediat, nu asteapta deloc
        # get(timeout=...) = blocant: asteapta pana la timeout sa apara un mesaj
        # Pentru P, vrem sa nu ne blocam mult; P trebuie sa ruleze periodic.
        if mod_curent == "automat":
            ultima_comanda = None
            try:
                # luam ce e disponibil acum, fara asteptare
                ultima_comanda = q_comenzi_automat.get_nowait()
                # folosim get_nowait() ca sa nu blocam P daca nu e nimic in coada
                # daca sunt mai multe, o pastram pe ultima (cea mai noua)
                while True:
                    try:
                        ultima_comanda = q_comenzi_automat.get_nowait()
                    except queue.Empty:
                        break
            except queue.Empty:
                ultima_comanda = None

            if ultima_comanda is not None:
                # comanda automata e un dict: {"timestamp":..., "putere":...}
                putere_curenta = ultima_comanda["putere"]

        # Crestere presiune daca puterea e mare + diminuare spre referinta
        crestere = 0.08* (putere_curenta / 100.0)
        diminuare = 0.01 * (configurare["presiune_referinta"] - presiune)
        presiune = presiune + crestere + diminuare

        # Decidem actiunea valvei in functie de presiune
        if presiune > configurare["presiune_maxima_siguranta"]:
            actiune_valva = 1.0
        elif presiune > configurare["presiune_referinta"] + 0.3:
            actiune_valva = 0.6
        else:
            actiune_valva = 0.0

        presiune -= 0.08 * actiune_valva
        presiune += random.uniform(-0.01, 0.01)
        # adaugam un zgomot la fiecare presiune

        # Trimitem presiunea catre S pentru afisare
        ultimul_mesaj(
    q_presiune,
    {"timestamp": time.monotonic(), "presiune": presiune, "valva": actiune_valva}
)


        # asteptare periodica fara busy-wait
        asteapta_pana_la_urmatoarea_activare(next_release, stop_event)

def task_s(configurare, stare, lock_stare, q_evenimente_sw, q_temperaturi, q_comenzi_automat, q_presiune, stop_event, lock_consola):
    # proceseaza evenimentele SW (manual/automat, setare putere manuala)
    # citeste temperatura cea mai recenta de la T
    # citeste presiunea cea mai recenta de la P
    # in modul automat: calculeaza puterea si o transmite catre P
    # in modul manual: nu calculeaza puterea (nu suprascrie), doar afiseaza starea
    
    # previne o secventa gresita de functionare:
    # daca SW e pe manual, S nu are voie sa calculeze/trimita comenzi de putere. In modul manual, S nu pune nimic in q_comenzi_automat
    
    # previne race condition: orice update la stare["mod"], stare["putere_*"] se face sub lock_stare

    ultima_temperatura = None
    ultima_presiune = None

    next_afisare = time.monotonic()

    while not stop_event.is_set():
        # procam toate evenimentele SW disponibile acum (neblocant)
        while True:
            try:
                ev = q_evenimente_sw.get_nowait()
            except queue.Empty:
                break

            tip = ev.get("tip")

            if tip == "oprire":
                stop_event.set()
                break

            if tip == "set_mod":
                mod_nou = ev.get("mod")
                if mod_nou in ("manual", "automat"):
                    with lock_stare:
                        stare["mod"] = mod_nou

                        # Daca am trecut in manual, punerea puterii curente devine exclusiva SW
                        if mod_nou == "manual":
                            stare["putere_curenta"] = stare["putere_manual"]

            if tip == "set_putere_manual":
                putere = ev.get("putere")
                if putere is not None:
                    putere = limiteaza(float(putere), 0.0, 100.0)
                    with lock_stare:
                        stare["putere_manual"] = putere
                        # daca suntem in manual, aplicam imediat puterea
                        if stare["mod"] == "manual":
                            stare["putere_curenta"] = stare["putere_manual"]

        if stop_event.is_set():
            break

        # citim temperatura cea mai recenta de la T 
        # q_temperaturi.get(timeout=0.1) inseamna: "astept maxim 0.1 sec sa apara un mesaj; daca nu apare, merg mai departe"
        # asta reduce consumul CPU 
        try:
            msg = q_temperaturi.get(timeout=0.1)
            ultima_temperatura = msg

            # Daca au venit mai multe, pastram ultimul (cel mai recent)
            while True:
                try:
                    ultima_temperatura = q_temperaturi.get_nowait()
                except queue.Empty:
                    break
        except queue.Empty:
            pass

        # citim presiunea cea mai recenta de la P
        try:
            ultima_presiune = q_presiune.get_nowait()
            while True:
                try:
                    ultima_presiune = q_presiune.get_nowait()
                except queue.Empty:
                    break
        except queue.Empty:
            pass

        # calulam temperatura medie si confortul
        if ultima_temperatura is not None:
            temperaturi = ultima_temperatura["temperaturi"]
            t_medie = sum(temperaturi) / len(temperaturi)
            confort = calcul_confort(t_medie, configurare["temperatura_referinta"], configurare["banda_confort"])
        else:
            t_medie = float("nan")
            confort = "necunoscut"

        # stabilim puterea curenta in functie de modul de functionare
        with lock_stare:
            mod_curent = stare["mod"]
            putere_manual = stare["putere_manual"]

        if mod_curent == "automat" and ultima_temperatura is not None:
            # mod automat: S calculeaza puterea
            putere_calc = calcul_putere_mod_automat(t_medie, configurare["temperatura_referinta"])
            putere_calc = limiteaza(putere_calc, 0.0, 100.0)

            # Update stare sub mutex
            with lock_stare:
                stare["putere_curenta"] = putere_calc

            # Trimitem comanda automata catre P 
            ultimul_mesaj(q_comenzi_automat, {"timestamp": time.monotonic(), "putere": putere_calc})

        else:
            # mod manual: S nu calculeaza puterea si nu trimite comenzi catre P.
            # puterea curenta este stabilita de SW (prin stare["putere_manual"]).
            with lock_stare:
                stare["putere_curenta"] = putere_manual

            # nu trimitem nimic pe q_comenzi_automat in manual
        
        # Afisam starea o data la perioada_afisare_S secunde
        acum = time.monotonic()
        if acum >= next_afisare:
            next_afisare = acum + configurare["perioada_afisare_S"]

            with lock_stare:
                mod_afis = stare["mod"]
                putere_afis = stare["putere_curenta"]

            pres = ultima_presiune["presiune"] if ultima_presiune is not None else float("nan")

            valva = ultima_presiune.get("valva", float("nan")) if ultima_presiune is not None else float("nan")

            with lock_consola:
                print(
                    f"[S] mod={mod_afis:7s} ; T_medie={t_medie:5.2f} C ; confort={confort:12s} ; "
                    f"presiune={pres:4.2f} ; putere={putere_afis:5.1f}% ; valva={valva:3.1f}"
                )

        # eliberam CPU-ul fara busy-wait
        stop_event.wait(timeout=0.02)
        
def main():
    # "configurare" contine parametrii sistemului 
    configurare = {
        # parametri confort
        "temperatura_referinta": 22.0, # temperatura tinta
        "banda_confort": 1.0, # +/- 1 grad C fata de tinta

        # parametri model temperatura 
        "temperatura_ambient": 18.0, # fara incalzire
        "delta_max_incalzire": 10.0, # cu cate grade urca peste ammbient la putere 100%
        "viteza_raspuns_temperatura": 0.08, # cat de repede urca/scade temperatura

        # parametri presiune
        "presiune_referinta": 3.0, # nivel normal de presiune
        "presiune_maxima_siguranta": 4.0, #prag de siguranta, peste, se deschide valva complet

        # perioade (secunde)
        "perioada_T": 0.5, # perioada de citire temperatura 
        "perioada_P": 0.2, # perioada de reglare presiune
        "perioada_afisare_S": 1.0, # perioada de afisare stare in S

        # numar termocupluri
        "numar_TC": 4, # cate termocupluri avem
    }

    # "stare" este zona partajata intre thread-uri. Orice citire/scriere din stare trebuie facuta sub lock_stare (mutex).
    # Asta previne secventa gresita "date incorecte intre S si P".
    stare = {
        "mod": "automat", 
        "putere_manual": 30.0, # setata de SW in mod manual
        "putere_curenta": 0.0, # actualizata de S si folosita de T si P
    }

    # Mutex (Lock) = excludere mutuala pentru "stare"
    lock_stare = threading.Lock() # pentru a proteja accesul la "stare"

    # Lock separat pentru print-uri ca sa nu se amestece liniile
    lock_consola = threading.Lock()

    # main seteaza stop_event, celelalte thread-uri verifica stop_event si ies
    stop_event = threading.Event()

    # Cozi de mesaje:
    # maxsize=1 pentru temperaturi/presiune/comenzi automate - pastram doar ultimul mesaj
    q_evenimente_sw = queue.Queue(maxsize=10) 
    q_temperaturi = queue.Queue(maxsize=1)
    q_comenzi_automat = queue.Queue(maxsize=1)
    q_presiune = queue.Queue(maxsize=1)

    # Thread-urile sunt create cu daemon=True.
    # daca thread-ul principal (main) se termina, thread-urile daemon nu mai tin procesul in viata.
    # util sa nu ramana procesul blocat.
    # facem si join(timeout) ca sa fim siguri ca se termina 
    th_sw = threading.Thread(target=task_sw, name="SW", args=(q_evenimente_sw, stop_event, lock_consola), daemon=True)
    th_t = threading.Thread(target=task_t, name="T", args=(configurare, stare, lock_stare, q_temperaturi, stop_event), daemon=True)
    th_p = threading.Thread(target=task_p, name="P", args=(configurare, stare, lock_stare, q_comenzi_automat, q_presiune, stop_event), daemon=True)
    th_s = threading.Thread(target=task_s, name="S", args=(configurare, stare, lock_stare, q_evenimente_sw, q_temperaturi, q_comenzi_automat, q_presiune, stop_event, lock_consola), daemon=True)

    # Pornim thread-urile
    th_t.start()
    th_p.start()
    th_s.start()
    th_sw.start()

    # Main asteapta oprirea fara busy-wait
    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        stop_event.set()

    # Asteptam terminarea thread-urilor cu timeout
    for th in (th_sw, th_t, th_s, th_p):
        try:
            th.join(timeout=1.0)
        except RuntimeError:
            pass

    with lock_consola:
        print("\n Oprire program")

if __name__ == "__main__":
    main()
