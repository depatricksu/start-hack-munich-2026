"""Reply mails for the booking flow: $0 LLM cost, but never the same text twice in a row.

Every mail = greeting + body + closing + sign-off. Each part has several variants per mail kind and language,
so one kind has dozens of combinations. The choice is seeded by the thread (the same thread always reads
consistently, e.g. a re-run gives the same text), and we skip the combination we used last time for that kind,
so two customers in a row never get identical mails. The customer's first name comes from the address
(anna.schmidt@... -> "Anna"); role addresses (info@, sales@, logistics@ ...) get a neutral greeting.

    render("booked", "de", values, thread_id=123, customer="anna.schmidt@x.mail")
values: ROUTE, AIRLINE, PRICE, REF, TRANSIT, SLOTS, FORWARDER
"""
import random, re, time
from core import db

ROLE = {"info", "sales", "logistics", "ops", "operations", "export", "import", "buyer", "procurement", "purchasing",
        "shipping", "office", "contact", "orders", "admin", "team", "cargo", "freight", "einkauf", "versand", "mail"}

GREET = {
    "en": {"name": ["Hi {NAME},", "Hello {NAME},", "Dear {NAME},", "Good morning {NAME},"],
           "anon": ["Hello,", "Hi there,", "Good morning,", "Hello and thanks for your mail,"]},
    "de": {"name": ["Hallo {NAME},", "Guten Tag {NAME},", "Liebe/r {NAME},", "Hallo {NAME}, danke für Ihre Nachricht."],
           "anon": ["Guten Tag,", "Hallo,", "Sehr geehrte Damen und Herren,"]},
    "it": {"name": ["Buongiorno {NAME},", "Gentile {NAME},", "Ciao {NAME},"],
           "anon": ["Buongiorno,", "Salve,", "Gentile cliente,"]},
    "fr": {"name": ["Bonjour {NAME},", "Bonjour {NAME}, j'espère que vous allez bien.", "Bonjour {NAME}, et merci pour votre message."],
           "anon": ["Bonjour,", "Madame, Monsieur,", "Bonjour à vous,"]},
    "es": {"name": ["Hola, {NAME}:", "Hola de nuevo, {NAME}:", "Hola {NAME}, gracias por su mensaje."],
           "anon": ["Hola:", "Hola de nuevo:", "Estimados señores:"]},
}
GREET["de"]["name"][2] = "Guten Tag {NAME},"          # no gendered forms (team rule: never Frau/Herr)

# Signed by a person, the same one who signs the quote (llm/extract.py SIGNER): never "your team", never the customer.
from llm.extract import SIGNER
SIGN = {
    "en": ["%s\n%s\nAir Export" % (x, SIGNER) for x in ("Best regards", "Kind regards", "Cheers", "Many thanks and best wishes")],
    "de": ["%s\n%s\nLuftfracht Export" % (x, SIGNER) for x in ("Viele Grüße", "Beste Grüße", "Freundliche Grüße", "Herzliche Grüße")],
    "it": ["%s\n%s\nExport Aereo" % (x, SIGNER) for x in ("Cordiali saluti", "Un cordiale saluto", "Grazie e buona giornata")],
    "fr": ["%s\n%s\nExport Aérien" % (x, SIGNER) for x in ("Bien cordialement", "Cordialement", "Bien à vous", "Bonne journée")],
    "es": ["%s\n%s\nExportación Aérea" % (x, SIGNER) for x in ("Un saludo", "Saludos cordiales", "Un cordial saludo")],
}

BODY = {
    "booked": {
        "en": ["thank you for your order. Your shipment {ROUTE} is booked with {AIRLINE} at {PRICE} all-in, booking reference {REF}.",
               "great, it's done: {ROUTE} is booked with {AIRLINE} for {PRICE} all-in. Your reference is {REF}.",
               "thanks for the go-ahead. We have booked {ROUTE} on {AIRLINE} at the quoted {PRICE} all-in (ref. {REF}).",
               "your booking is in. {AIRLINE} will carry your shipment {ROUTE}, total {PRICE} all-in, reference {REF}."],
        "de": ["vielen Dank für Ihren Auftrag. Ihre Sendung {ROUTE} ist bei {AIRLINE} zum Gesamtpreis von {PRICE} gebucht, Buchungsnummer {REF}.",
               "erledigt: {ROUTE} ist bei {AIRLINE} für {PRICE} all-in gebucht. Ihre Referenz lautet {REF}.",
               "danke für die Freigabe. Wir haben {ROUTE} bei {AIRLINE} zum angebotenen Preis von {PRICE} gebucht (Ref. {REF}).",
               "Ihre Buchung steht. {AIRLINE} übernimmt Ihre Sendung {ROUTE}, Gesamtpreis {PRICE}, Referenz {REF}."],
        "it": ["grazie per la conferma. La spedizione {ROUTE} è prenotata con {AIRLINE} a {PRICE} all-in, riferimento prenotazione {REF}.",
               "fatto: abbiamo prenotato {ROUTE} con {AIRLINE} a {PRICE} all-in. Il vostro riferimento è {REF}.",
               "grazie per l'ok. Abbiamo prenotato {ROUTE} con {AIRLINE} al prezzo offerto di {PRICE} all-in (rif. {REF})."],
        "fr": ["merci pour votre commande. Votre envoi {ROUTE} est réservé avec {AIRLINE} à {PRICE} tout compris, référence de réservation {REF}.",
               "c'est fait : {ROUTE} est réservé chez {AIRLINE} pour {PRICE} tout compris. Votre référence est {REF}.",
               "merci pour votre feu vert. Nous avons réservé {ROUTE} chez {AIRLINE} au tarif proposé de {PRICE} tout compris (réf. {REF})."],
        "es": ["gracias por su pedido. Su envío {ROUTE} queda reservado con {AIRLINE} por {PRICE} todo incluido, referencia de reserva {REF}.",
               "listo: {ROUTE} está reservado con {AIRLINE} por {PRICE} todo incluido. Su referencia es {REF}.",
               "gracias por darnos el visto bueno. Hemos reservado {ROUTE} con {AIRLINE} al precio ofertado de {PRICE} todo incluido (ref. {REF})."]},
    "requested": {
        "en": ["thank you for your order. We have sent the booking for {ROUTE} to {AIRLINE} at {PRICE} all-in (our reference {REF}).",
               "thanks, we are on it: the booking request for {ROUTE} has gone to {AIRLINE}, {PRICE} all-in, reference {REF}.",
               "great, we have asked {AIRLINE} to book {ROUTE} at {PRICE} all-in. Our reference is {REF}."],
        "de": ["vielen Dank für Ihren Auftrag. Die Buchung {ROUTE} zum Gesamtpreis von {PRICE} ist bei {AIRLINE} angefragt (Referenz {REF}).",
               "danke, wir kümmern uns: Die Buchungsanfrage für {ROUTE} ist an {AIRLINE} raus, {PRICE} all-in, Referenz {REF}.",
               "prima, wir haben {AIRLINE} gebeten, {ROUTE} zu {PRICE} all-in zu buchen. Unsere Referenz: {REF}."],
        "it": ["grazie per l'ordine. Abbiamo inoltrato a {AIRLINE} la richiesta di prenotazione per {ROUTE} a {PRICE} all-in (nostro riferimento {REF}).",
               "ricevuto, ci pensiamo noi: la richiesta di booking per {ROUTE} è partita verso {AIRLINE}, {PRICE} all-in, riferimento {REF}.",
               "perfetto, abbiamo chiesto a {AIRLINE} di prenotare {ROUTE} a {PRICE} all-in. Il nostro riferimento è {REF}."],
        "fr": ["merci pour votre commande. Nous avons transmis la réservation {ROUTE} à {AIRLINE} à {PRICE} tout compris (notre référence {REF}).",
               "merci, on s'en occupe : la demande de réservation pour {ROUTE} est partie chez {AIRLINE}, {PRICE} tout compris, référence {REF}.",
               "parfait, nous avons demandé à {AIRLINE} de réserver {ROUTE} à {PRICE} tout compris. Notre référence : {REF}."],
        "es": ["gracias por su pedido. Hemos enviado a {AIRLINE} la reserva de {ROUTE} por {PRICE} todo incluido (nuestra referencia {REF}).",
               "gracias, nos ponemos con ello: la solicitud de reserva para {ROUTE} ya ha salido hacia {AIRLINE}, {PRICE} todo incluido, referencia {REF}.",
               "perfecto, hemos pedido a {AIRLINE} que reserve {ROUTE} por {PRICE} todo incluido. Nuestra referencia es {REF}."]},
    "confirmed": {
        "en": ["good news: {AIRLINE} has confirmed your shipment {ROUTE}, booking {REF}. It is ready to ship, expected transit {TRANSIT} days.",
               "{AIRLINE} just confirmed booking {REF} for {ROUTE}. Everything is set, transit should be about {TRANSIT} days.",
               "your shipment {ROUTE} is confirmed by {AIRLINE} (booking {REF}) and ready to go. Expected transit: {TRANSIT} days."],
        "de": ["gute Nachrichten: {AIRLINE} hat Ihre Sendung {ROUTE} bestätigt, Buchung {REF}. Sie ist versandbereit, Laufzeit ca. {TRANSIT} Tage.",
               "{AIRLINE} hat die Buchung {REF} für {ROUTE} soeben bestätigt. Alles steht, die Laufzeit liegt bei etwa {TRANSIT} Tagen.",
               "Ihre Sendung {ROUTE} ist von {AIRLINE} bestätigt (Buchung {REF}) und startklar. Voraussichtliche Laufzeit: {TRANSIT} Tage."],
        "it": ["buone notizie: {AIRLINE} ha confermato la vostra spedizione {ROUTE}, prenotazione {REF}. È pronta a partire, con un transit time previsto di {TRANSIT} giorni.",
               "{AIRLINE} ha appena confermato la prenotazione {REF} per {ROUTE}. È tutto a posto, il transito sarà di circa {TRANSIT} giorni.",
               "la spedizione {ROUTE} è confermata da {AIRLINE} (prenotazione {REF}) e pronta a partire. Tempo di transito previsto: {TRANSIT} giorni."],
        "fr": ["bonne nouvelle : {AIRLINE} a confirmé votre envoi {ROUTE}, réservation {REF}. Il est prêt à partir, avec un transit prévu d'environ {TRANSIT} jours.",
               "{AIRLINE} vient de confirmer la réservation {REF} pour {ROUTE}. Tout est en place, le transit devrait être d'environ {TRANSIT} jours.",
               "votre envoi {ROUTE} est confirmé par {AIRLINE} (réservation {REF}) et prêt au départ. Délai de transit prévu : {TRANSIT} jours."],
        "es": ["buenas noticias: {AIRLINE} ha confirmado su envío {ROUTE}, reserva {REF}. Está listo para salir, con un tránsito previsto de {TRANSIT} días.",
               "{AIRLINE} acaba de confirmar la reserva {REF} para {ROUTE}. Todo está en orden, el tránsito será de unos {TRANSIT} días.",
               "su envío {ROUTE} está confirmado por {AIRLINE} (reserva {REF}) y listo para salir. Tránsito previsto: {TRANSIT} días."]},
    "price_changed": {
        "en": ["one thing before we finalise: when we placed the booking for {ROUTE}, {AIRLINE} came back with a higher price. All-in it is now {NEW_PRICE} instead of the {PRICE} we quoted.",
               "a quick heads-up on {ROUTE}: {AIRLINE} changed its price at booking. The new all-in total is {NEW_PRICE}, not the {PRICE} from our quote.",
               "we went to book {ROUTE} with {AIRLINE}, and the airline's price had moved in the meantime: {NEW_PRICE} all-in instead of {PRICE}."],
        "de": ["eine Sache vorab: Bei der Buchung für {ROUTE} hat {AIRLINE} einen höheren Preis bestätigt. All-in sind es jetzt {NEW_PRICE} statt der angebotenen {PRICE}.",
               "ein kurzer Hinweis zu {ROUTE}: {AIRLINE} hat den Preis bei der Buchung geändert. Der neue Gesamtpreis beträgt {NEW_PRICE}, nicht {PRICE} wie in unserem Angebot.",
               "wir wollten {ROUTE} bei {AIRLINE} buchen, und der Preis der Airline hat sich inzwischen geändert: {NEW_PRICE} all-in statt {PRICE}."],
        "it": ["una cosa prima di chiudere: al momento della prenotazione per {ROUTE}, {AIRLINE} ci ha comunicato un prezzo più alto. Il totale all-in ora è {NEW_PRICE}, invece di {PRICE} come da nostra offerta.",
               "un aggiornamento veloce su {ROUTE}: in fase di prenotazione {AIRLINE} ha modificato la tariffa. Il nuovo totale all-in è {NEW_PRICE}, non più {PRICE} come nella nostra offerta.",
               "siamo andati a prenotare {ROUTE} con {AIRLINE} e nel frattempo la tariffa della compagnia è cambiata: {NEW_PRICE} all-in invece di {PRICE}."],
        "fr": ["un point avant de finaliser : au moment de la réservation pour {ROUTE}, {AIRLINE} nous a annoncé un tarif plus élevé. Le total tout compris passe à {NEW_PRICE}, au lieu de {PRICE} dans notre offre.",
               "petite information sur {ROUTE} : {AIRLINE} a modifié son tarif au moment de la réservation. Le nouveau total tout compris est de {NEW_PRICE}, et non plus {PRICE} comme dans notre offre.",
               "nous avons voulu réserver {ROUTE} avec {AIRLINE}, mais entre-temps le tarif de la compagnie a bougé : {NEW_PRICE} tout compris au lieu de {PRICE}."],
        "es": ["un detalle antes de cerrar: al hacer la reserva de {ROUTE}, {AIRLINE} nos ha confirmado un precio más alto. El total todo incluido es ahora {NEW_PRICE}, en lugar de {PRICE} como figuraba en nuestra oferta.",
               "le aviso de un cambio en {ROUTE}: {AIRLINE} ha modificado su tarifa al reservar. El nuevo total todo incluido es {NEW_PRICE}, no {PRICE} como en nuestra oferta.",
               "fuimos a reservar {ROUTE} con {AIRLINE} y, mientras tanto, la tarifa de la aerolínea había cambiado: {NEW_PRICE} todo incluido en lugar de {PRICE}."]},
    "faster_option": {
        "en": ["yes, we can go faster: {ALT_AIRLINE} takes {ROUTE} in about {ALT_TRANSIT} days for {ALT_PRICE} all-in (our first offer was {PRICE}).",
               "good question. The quickest we have is {ALT_AIRLINE}: about {ALT_TRANSIT} days for {ROUTE}, {ALT_PRICE} all-in instead of {PRICE}.",
               "we checked the faster options. {ALT_AIRLINE} can fly {ROUTE} in about {ALT_TRANSIT} days, {ALT_PRICE} all-in."],
        "de": ["ja, es geht schneller: {ALT_AIRLINE} fliegt {ROUTE} in ca. {ALT_TRANSIT} Tagen für {ALT_PRICE} all-in (unser erstes Angebot: {PRICE}).",
               "gute Frage. Am schnellsten ist {ALT_AIRLINE}: ca. {ALT_TRANSIT} Tage für {ROUTE}, {ALT_PRICE} all-in statt {PRICE}.",
               "wir haben die schnelleren Optionen geprüft. {ALT_AIRLINE} schafft {ROUTE} in ca. {ALT_TRANSIT} Tagen, {ALT_PRICE} all-in."],
        "it": ["sì, possiamo fare più in fretta: {ALT_AIRLINE} porta {ROUTE} in circa {ALT_TRANSIT} giorni a {ALT_PRICE} all-in (la nostra prima offerta era {PRICE}).",
               "buona domanda. L'opzione più rapida che abbiamo è {ALT_AIRLINE}: circa {ALT_TRANSIT} giorni per {ROUTE}, {ALT_PRICE} all-in invece di {PRICE}.",
               "abbiamo verificato le soluzioni più veloci. {ALT_AIRLINE} copre {ROUTE} in circa {ALT_TRANSIT} giorni, a {ALT_PRICE} all-in."],
        "fr": ["oui, on peut aller plus vite : {ALT_AIRLINE} achemine {ROUTE} en environ {ALT_TRANSIT} jours pour {ALT_PRICE} tout compris (notre première offre était à {PRICE}).",
               "bonne question. Le plus rapide que nous ayons, c'est {ALT_AIRLINE} : environ {ALT_TRANSIT} jours pour {ROUTE}, {ALT_PRICE} tout compris au lieu de {PRICE}.",
               "nous avons regardé les options plus rapides. {ALT_AIRLINE} peut assurer {ROUTE} en environ {ALT_TRANSIT} jours, {ALT_PRICE} tout compris."],
        "es": ["sí, podemos ir más rápido: {ALT_AIRLINE} lleva {ROUTE} en unos {ALT_TRANSIT} días por {ALT_PRICE} todo incluido (nuestra primera oferta era de {PRICE}).",
               "buena pregunta. Lo más rápido que tenemos es {ALT_AIRLINE}: unos {ALT_TRANSIT} días para {ROUTE}, {ALT_PRICE} todo incluido en lugar de {PRICE}.",
               "hemos revisado las opciones más rápidas. {ALT_AIRLINE} puede volar {ROUTE} en unos {ALT_TRANSIT} días, {ALT_PRICE} todo incluido."]},
    "cheaper_option": {
        "en": ["thanks for the feedback. We can offer {ALT_AIRLINE} for {ROUTE} at {ALT_PRICE} all-in instead of {PRICE}, transit about {ALT_TRANSIT} days.",
               "good news on price: with {ALT_AIRLINE} we can do {ROUTE} for {ALT_PRICE} all-in (transit about {ALT_TRANSIT} days), down from {PRICE}.",
               "we had another look. {ALT_AIRLINE} can take {ROUTE} for {ALT_PRICE} all-in, a bit slower at about {ALT_TRANSIT} days."],
        "de": ["danke für Ihr Feedback. Statt {PRICE} können wir {ROUTE} mit {ALT_AIRLINE} für {ALT_PRICE} all-in anbieten, Laufzeit ca. {ALT_TRANSIT} Tage.",
               "gute Nachrichten zum Preis: Mit {ALT_AIRLINE} geht {ROUTE} für {ALT_PRICE} all-in (Laufzeit ca. {ALT_TRANSIT} Tage), statt {PRICE}.",
               "wir haben noch einmal geschaut. {ALT_AIRLINE} übernimmt {ROUTE} für {ALT_PRICE} all-in, etwas langsamer mit ca. {ALT_TRANSIT} Tagen."],
        "it": ["grazie per il riscontro. Per {ROUTE} possiamo proporvi {ALT_AIRLINE} a {ALT_PRICE} all-in invece di {PRICE}, con un transito di circa {ALT_TRANSIT} giorni.",
               "buone notizie sul prezzo: con {ALT_AIRLINE} possiamo fare {ROUTE} a {ALT_PRICE} all-in (transito di circa {ALT_TRANSIT} giorni), invece di {PRICE}.",
               "abbiamo ricontrollato le alternative per voi. {ALT_AIRLINE} può prendere {ROUTE} a {ALT_PRICE} all-in; è un po' più lenta, il transito è di circa {ALT_TRANSIT} giorni."],
        "fr": ["merci pour votre retour. Sur {ROUTE}, nous pouvons vous proposer {ALT_AIRLINE} à {ALT_PRICE} tout compris au lieu de {PRICE}, avec un transit d'environ {ALT_TRANSIT} jours.",
               "bonne nouvelle côté prix : avec {ALT_AIRLINE}, nous pouvons faire {ROUTE} pour {ALT_PRICE} tout compris (transit d'environ {ALT_TRANSIT} jours), au lieu de {PRICE}.",
               "nous avons regardé de nouveau. {ALT_AIRLINE} peut prendre {ROUTE} pour {ALT_PRICE} tout compris, un peu plus lent avec environ {ALT_TRANSIT} jours de transit."],
        "es": ["gracias por sus comentarios. Para {ROUTE} podemos ofrecerle {ALT_AIRLINE} por {ALT_PRICE} todo incluido en lugar de {PRICE}, con un tránsito de unos {ALT_TRANSIT} días.",
               "buenas noticias en precio: con {ALT_AIRLINE} podemos hacer {ROUTE} por {ALT_PRICE} todo incluido (tránsito de unos {ALT_TRANSIT} días), frente a {PRICE}.",
               "lo hemos vuelto a mirar. {ALT_AIRLINE} puede llevar {ROUTE} por {ALT_PRICE} todo incluido, algo más lento, con unos {ALT_TRANSIT} días de tránsito."]},
    "best_rate": {
        "en": ["thanks for the feedback. We compared all airlines on {ROUTE}, and {PRICE} all-in with {AIRLINE} is the best rate available right now.",
               "we understand. {PRICE} all-in is honestly the sharpest rate we can get for {ROUTE} today, after checking every carrier on the lane.",
               "thanks for asking. We already quoted the lowest rate on {ROUTE}: {AIRLINE} at {PRICE} all-in."],
        "de": ["danke für Ihr Feedback. Wir haben alle Airlines für {ROUTE} verglichen, {PRICE} all-in mit {AIRLINE} ist aktuell die beste Rate.",
               "verstehen wir. {PRICE} all-in ist ehrlich gesagt die beste Rate, die wir heute für {ROUTE} bekommen, nach Prüfung aller Carrier.",
               "danke für die Nachfrage. Wir haben bereits die günstigste Rate für {ROUTE} angeboten: {AIRLINE} zu {PRICE} all-in."],
        "it": ["grazie per il riscontro. Abbiamo confrontato tutte le compagnie su {ROUTE} e {PRICE} all-in con {AIRLINE} è la tariffa migliore disponibile al momento.",
               "capiamo bene. {PRICE} all-in è davvero la tariffa più competitiva che riusciamo a ottenere oggi per {ROUTE}, dopo aver sentito tutti i vettori sulla tratta.",
               "grazie per la domanda. Vi abbiamo già quotato la tariffa più bassa su {ROUTE}: {AIRLINE} a {PRICE} all-in."],
        "fr": ["merci pour votre retour. Nous avons comparé toutes les compagnies sur {ROUTE}, et {PRICE} tout compris avec {AIRLINE} est le meilleur tarif disponible à ce jour.",
               "nous comprenons. {PRICE} tout compris est vraiment le tarif le plus serré que nous puissions obtenir aujourd'hui sur {ROUTE}, après avoir consulté toutes les compagnies de la ligne.",
               "merci pour la question. Nous vous avons déjà proposé le tarif le plus bas sur {ROUTE} : {AIRLINE} à {PRICE} tout compris."],
        "es": ["gracias por sus comentarios. Hemos comparado todas las aerolíneas en {ROUTE} y {PRICE} todo incluido con {AIRLINE} es la mejor tarifa disponible ahora mismo.",
               "lo entendemos. {PRICE} todo incluido es, sinceramente, la tarifa más ajustada que podemos conseguir hoy para {ROUTE}, después de consultar a todas las aerolíneas de la ruta.",
               "gracias por preguntar. Ya le ofrecimos la tarifa más baja en {ROUTE}: {AIRLINE} por {PRICE} todo incluido."]},
    "meeting": {
        "en": ["thank you for the feedback on the price. Our quote of {PRICE} is already based on the best rate we found for {ROUTE}, "
               "but we are happy to look at the options together (dates, routing, volume). {FORWARDER} from our team can call you at:\n\n{SLOTS}",
               "understood, price matters. {PRICE} is the best rate we found for {ROUTE} today, but there may be room with other dates or "
               "routings. {FORWARDER} would be glad to talk it through with you. Free times:\n\n{SLOTS}",
               "thanks for your honest feedback. Let's see what we can do on {ROUTE}: {FORWARDER} from our team can go through the options "
               "with you in a short call. Would one of these times work?\n\n{SLOTS}"],
        "de": ["vielen Dank für Ihre Rückmeldung zum Preis. Unser Angebot über {PRICE} basiert bereits auf der besten Rate für {ROUTE}, "
               "aber wir schauen uns die Möglichkeiten gerne gemeinsam an (Termine, Routing, Volumen). {FORWARDER} kann Sie anrufen am:\n\n{SLOTS}",
               "verstanden, der Preis ist wichtig. {PRICE} ist heute die beste Rate für {ROUTE}, mit anderen Terminen oder Routings ist "
               "eventuell mehr drin. {FORWARDER} bespricht das gerne mit Ihnen. Freie Termine:\n\n{SLOTS}",
               "danke für das offene Feedback. Schauen wir gemeinsam, was bei {ROUTE} möglich ist: {FORWARDER} aus unserem Team geht die "
               "Optionen gerne in einem kurzen Gespräch mit Ihnen durch. Passt einer dieser Termine?\n\n{SLOTS}"],
        "it": ["grazie per il riscontro sul prezzo. La nostra offerta di {PRICE} si basa già sulla tariffa migliore trovata per {ROUTE}, "
               "ma valutiamo volentieri insieme le alternative (date, routing, volumi). {FORWARDER} del nostro team può chiamarvi in uno di questi orari:\n\n{SLOTS}",
               "capito, il prezzo conta. {PRICE} è la tariffa migliore che abbiamo trovato oggi per {ROUTE}, ma con altre date o un altro "
               "routing potrebbe esserci margine. {FORWARDER} ne parla volentieri con voi. Orari disponibili:\n\n{SLOTS}",
               "grazie per la franchezza. Vediamo cosa si può fare su {ROUTE}: {FORWARDER} del nostro team può illustrarvi le opzioni "
               "in una breve telefonata. Uno di questi orari vi va bene?\n\n{SLOTS}"],
        "fr": ["merci pour votre retour sur le prix. Notre offre à {PRICE} repose déjà sur le meilleur tarif trouvé pour {ROUTE}, "
               "mais nous regardons volontiers les options avec vous (dates, routage, volumes). {FORWARDER} de notre équipe peut vous appeler à l'un de ces créneaux :\n\n{SLOTS}",
               "entendu, le prix compte. {PRICE} est le meilleur tarif trouvé aujourd'hui pour {ROUTE}, mais d'autres dates ou un autre "
               "routage peuvent laisser de la marge. {FORWARDER} en discute volontiers avec vous. Créneaux disponibles :\n\n{SLOTS}",
               "merci pour votre franchise. Voyons ensemble ce qui est possible sur {ROUTE} : {FORWARDER} de notre équipe peut vous présenter "
               "les options lors d'un court appel. L'un de ces créneaux vous convient-il ?\n\n{SLOTS}"],
        "es": ["gracias por sus comentarios sobre el precio. Nuestra oferta de {PRICE} ya se basa en la mejor tarifa que encontramos para {ROUTE}, "
               "pero con gusto revisamos las opciones con usted (fechas, ruta, volumen). {FORWARDER}, de nuestro equipo, puede llamarle en estos horarios:\n\n{SLOTS}",
               "entendido, el precio importa. {PRICE} es la mejor tarifa que hemos encontrado hoy para {ROUTE}, pero con otras fechas o rutas "
               "puede haber margen. {FORWARDER} lo puede comentar con usted con mucho gusto. Horarios libres:\n\n{SLOTS}",
               "gracias por su sinceridad. Veamos qué podemos hacer en {ROUTE}: {FORWARDER}, de nuestro equipo, puede repasar las opciones "
               "con usted en una llamada breve. ¿Le viene bien alguno de estos horarios?\n\n{SLOTS}"]},
}
CLOSE = {
    "booked": {"en": ["We will let you know as soon as the airline has confirmed it.", "You'll hear from us once the airline confirms.",
                      "We'll send the confirmation as soon as it arrives."],
               "de": ["Sobald die Airline bestätigt hat, melden wir uns.", "Die Bestätigung der Airline schicken wir Ihnen umgehend weiter.",
                      "Wir melden uns, sobald die Bestätigung da ist."],
               "it": ["Vi aggiorniamo appena la compagnia aerea conferma.", "Vi inoltriamo la conferma della compagnia non appena arriva.",
                      "Ci risentiamo appena abbiamo la conferma."],
               "fr": ["Nous revenons vers vous dès que la compagnie a confirmé.", "Nous vous transmettons la confirmation de la compagnie dès réception.",
                      "Nous vous recontactons dès que la confirmation arrive."],
               "es": ["Le avisamos en cuanto la aerolínea lo confirme.", "Le reenviamos la confirmación de la aerolínea en cuanto llegue.",
                      "Volvemos a escribirle en cuanto tengamos la confirmación."]},
    "requested": {"en": ["You will hear from us as soon as it is confirmed.", "We'll be back in touch once the airline confirms."],
                  "de": ["Sobald sie bestätigt ist, melden wir uns.", "Wir melden uns, sobald die Airline bestätigt."],
                  "it": ["Vi facciamo sapere appena è confermata.", "Vi ricontattiamo non appena la compagnia aerea conferma."],
                  "fr": ["Nous revenons vers vous dès que c'est confirmé.", "Nous vous recontactons dès confirmation de la compagnie."],
                  "es": ["Le escribimos en cuanto esté confirmada.", "Volvemos a contactarle cuando la aerolínea confirme."]},
    "confirmed": {"en": ["Just reply here if you need a status update.", "If you need anything else, simply reply to this mail.",
                         "Questions about the shipment? Reply here any time."],
                  "de": ["Für einen Status antworten Sie einfach hier.", "Wenn Sie noch etwas brauchen, antworten Sie einfach auf diese Mail.",
                         "Fragen zur Sendung? Antworten Sie jederzeit hier."],
                  "it": ["Per un aggiornamento sullo stato basta rispondere a questa mail.", "Se vi serve altro, rispondete pure a questa mail.",
                         "Domande sulla spedizione? Rispondete qui quando volete."],
                  "fr": ["Pour un point sur le statut, il suffit de répondre à ce mail.", "Besoin d'autre chose ? Répondez simplement à ce mail.",
                         "Une question sur l'envoi ? Répondez ici à tout moment."],
                  "es": ["Si necesita una actualización del estado, responda a este correo.", "Si necesita algo más, basta con responder a este correo.",
                         "¿Alguna pregunta sobre el envío? Responda aquí cuando quiera."]},
    "price_changed": {"en": ["Are you happy to go ahead at {NEW_PRICE}? A short yes or no is enough.",
                             "Shall we keep the booking at the new price? Just reply yes or no.",
                             "Would you like us to go ahead at {NEW_PRICE}? Let us know either way."],
                      "de": ["Sollen wir zu {NEW_PRICE} buchen? Ein kurzes Ja oder Nein genügt.",
                             "Möchten Sie die Buchung zum neuen Preis behalten? Antworten Sie einfach mit Ja oder Nein.",
                             "Dürfen wir zu {NEW_PRICE} fortfahren? Geben Sie uns bitte kurz Bescheid."],
                      "it": ["Procediamo a {NEW_PRICE}? Basta un sì o un no.",
                             "Confermiamo la prenotazione al nuovo prezzo? Ci basta un sì o un no.",
                             "Volete che procediamo a {NEW_PRICE}? Fateci sapere in ogni caso."],
                      "fr": ["Pouvons-nous confirmer à {NEW_PRICE} ? Un simple oui ou non suffit.",
                             "Souhaitez-vous maintenir la réservation au nouveau tarif ? Répondez simplement oui ou non.",
                             "Voulez-vous que nous poursuivions à {NEW_PRICE} ? Dites-le-nous dans un sens ou dans l'autre."],
                      "es": ["¿Seguimos adelante a {NEW_PRICE}? Basta con un sí o un no.",
                             "¿Mantenemos la reserva al nuevo precio? Responda simplemente sí o no.",
                             "¿Quiere que sigamos a {NEW_PRICE}? Díganos algo en cualquier caso."]},
    "faster_option": {"en": ["Just reply 'book it' and we'll take care of the rest.", "Shall we book it? A short yes is enough.",
                             "Reply with a go-ahead and we book it right away."],
                      "de": ["Antworten Sie einfach mit 'buchen', den Rest erledigen wir.", "Sollen wir buchen? Ein kurzes Ja genügt.",
                             "Mit Ihrer Freigabe buchen wir sofort."],
                      "it": ["Rispondete pure 'prenota' e pensiamo noi al resto.", "Procediamo con la prenotazione? Basta un sì.",
                             "Con il vostro ok prenotiamo subito."],
                      "fr": ["Répondez simplement « on réserve » et nous nous occupons du reste.", "On réserve ? Un simple oui suffit.",
                             "Avec votre accord, nous réservons tout de suite."],
                      "es": ["Responda simplemente 'reservar' y nos encargamos del resto.", "¿Lo reservamos? Basta con un sí.",
                             "Con su visto bueno, lo reservamos enseguida."]},
    "cheaper_option": {"en": ["Just reply 'book it' and we'll take care of the rest.", "Shall we book it? A short yes is enough.",
                              "Reply with a go-ahead and we book it right away."],
                       "de": ["Antworten Sie einfach mit 'buchen', den Rest erledigen wir.", "Sollen wir buchen? Ein kurzes Ja genügt.",
                              "Mit Ihrer Freigabe buchen wir sofort."],
                       "it": ["Rispondete pure 'prenota' e pensiamo noi al resto.", "Procediamo con la prenotazione? Basta un sì.",
                              "Con il vostro ok prenotiamo subito."],
                       "fr": ["Répondez simplement « on réserve » et nous nous occupons du reste.", "On réserve ? Un simple oui suffit.",
                              "Avec votre accord, nous réservons tout de suite."],
                       "es": ["Responda simplemente 'reservar' y nos encargamos del resto.", "¿Lo reservamos? Basta con un sí.",
                              "Con su visto bueno, lo reservamos enseguida."]},
    "best_rate": {"en": ["The offer stays valid for today, just reply 'book it' if you'd like to go ahead.",
                         "If it works for you, a short 'yes, book it' is all we need.",
                         "Happy to book it whenever you are ready."],
                  "de": ["Das Angebot gilt heute weiter, antworten Sie einfach mit 'buchen', wenn Sie möchten.",
                         "Wenn es für Sie passt, genügt ein kurzes 'Ja, bitte buchen'.",
                         "Wir buchen gerne, sobald Sie bereit sind."],
                  "it": ["L'offerta resta valida per oggi: se volete procedere, basta rispondere 'prenota'.",
                         "Se per voi va bene, ci basta un 'sì, prenota'.",
                         "Prenotiamo volentieri appena ci date l'ok."],
                  "fr": ["L'offre reste valable aujourd'hui : répondez simplement « on réserve » si vous souhaitez y aller.",
                         "Si cela vous convient, un simple « oui, on réserve » nous suffit.",
                         "Nous réservons volontiers dès que vous nous donnez le feu vert."],
                  "es": ["La oferta sigue vigente hoy; si quiere seguir adelante, responda simplemente 'reservar'.",
                         "Si le encaja, nos basta con un 'sí, reservar'.",
                         "Lo reservamos con gusto en cuanto nos dé el visto bueno."]},
    "meeting": {"en": ["Just reply with the time that suits you best.", "Simply reply with your preferred slot.",
                       "Let us know which one works, or suggest another time."],
                "de": ["Antworten Sie einfach mit dem Termin, der Ihnen am besten passt.", "Nennen Sie uns einfach Ihren Wunschtermin.",
                       "Sagen Sie uns, welcher passt, oder schlagen Sie eine andere Zeit vor."],
                "it": ["Rispondete pure con l'orario che preferite.", "Indicateci semplicemente l'orario più comodo per voi.",
                       "Fateci sapere quale va bene, oppure proponeteci un altro orario."],
                "fr": ["Répondez simplement avec le créneau qui vous arrange.", "Indiquez-nous simplement le créneau de votre choix.",
                       "Dites-nous lequel vous convient, ou proposez-nous un autre horaire."],
                "es": ["Responda simplemente con el horario que mejor le venga.", "Indíquenos sin más el horario que prefiera.",
                       "Díganos cuál le viene bien, o proponga otro horario."]},
}


def _signed(thread_id):
    """The first name the customer signed the request with (humanize/, Riky), so the booking mails greet the same
    person as the quote did."""
    try:
        from llm import human
        row = db.con().execute("SELECT body FROM mails WHERE id=?", (thread_id,)).fetchone()
        return human.signed_name(row[0]) if row else None
    except Exception:
        return None


def first_name(address):
    """anna.schmidt@x -> Anna; j.doe@x -> None (initial only); sales@x -> None; auer-maschinenbau@x -> None
    (a company mailbox: "Hello Auer," went out to Tobias Auer's company, the jury reads that as a robot)."""
    local = (address or "").split("@")[0].lower()
    if "-" in local and "." not in local:
        return None
    part = re.split(r"[._\-+]", local)[0]
    if part in ROLE or len(part) < 2 or not part.isalpha():
        return None
    return part.capitalize()


def combos(kind, lang):
    lang = lang if lang in BODY[kind] else "en"
    return lang, (len(GREET[lang]["name"]), len(BODY[kind][lang]), len(CLOSE[kind][lang]), len(SIGN[lang]))


def render(kind, lang, values, thread_id=0, customer=""):
    lang, sizes = combos(kind, lang)
    rng = random.Random("%s:%s" % (thread_id, kind))
    pick = [rng.randrange(n) for n in sizes]
    key, last = "reply_variant:%s:%s" % (kind, lang), None
    try:
        last = db.get_state(key)
    except Exception:
        pass
    if last == ",".join(map(str, pick)):                     # same as the previous mail of this kind: rotate the body
        pick[1] = (pick[1] + 1) % sizes[1]
        pick[0] = (pick[0] + 1) % sizes[0]
    try:
        db.set_state(key, ",".join(map(str, pick)))
    except Exception:
        pass
    from llm import human
    name = _signed(thread_id) or first_name(customer)        # the person who signed the request, else from the address
    greet = (GREET[lang]["name"][pick[0]].replace("{NAME}", name) if name
             else GREET[lang]["anon"][pick[0] % len(GREET[lang]["anon"])])
    if greet.startswith("Good morning"):                     # only before noon (Berlin), a booking can come at 18:00
        hour = human._berlin(time.time()).hour
        greet = greet.replace("Good morning", "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening", 1)
    body = BODY[kind][lang][pick[1]]
    body = body[:1].upper() + body[1:] if body[:1] != "{" else body
    text = "%s\n\n%s\n\n%s\n\n%s" % (greet, body, CLOSE[kind][lang][pick[2]], SIGN[lang][pick[3]])
    for k, v in values.items():
        text = text.replace("{%s}" % k, str(v))
    return text, ",".join(map(str, pick))
