// ==========================================
// MOCK APIS & DATA (Do Not Deviate)
// ==========================================

// Mock: POST /query response shape
const mockEvents = [
    { event_id: "ev_lhr_01", name: "Open Mic & Social Night", activity_type: "Social / Music", location: "The Colony, Gulberg", lat: 31.5125, lng: 74.3458, time: "19:00 - 22:00", price: "1000 PKR" },
    { event_id: "ev_lhr_02", name: "Sufi Qawwali Evening", activity_type: "Cultural Night", location: "Alhamra Arts Council", lat: 31.5543, lng: 74.3318, time: "20:00 - 23:00", price: "1500 PKR" },
    { event_id: "ev_lhr_03", name: "Board Game Mixer", activity_type: "Social Gaming", location: "Unwind Cafe, DHA", lat: 31.4789, lng: 74.3912, time: "18:00 - 21:00", price: "1200 PKR" },
    { event_id: "ev_lhr_04", name: "Stand-up Comedy Showcase", activity_type: "Comedy", location: "Kickstart, Gulberg", lat: 31.5204, lng: 74.3587, time: "20:30 - 22:00", price: "2000 PKR" }
];

async function mockQuery(requestData) {
    console.log("Mock POST /query:", requestData);
    return { matches: mockEvents };
}

async function mockBook(requestData) {
    console.log("Mock POST /book:", requestData);
    const text = encodeURIComponent(`Hi, I'd like to book ${requestData.name} (ID: ${requestData.event_id}). I found you via Outsy!`);
    return { wa_link: `https://wa.me/923000000000?text=${text}` };
}

// ==========================================
// CORE MAP & CHAT LOGIC
// ==========================================

// Initialize the Map (Centered on Lahore)
const map = L.map('map', { zoomControl: false }).setView([31.5204, 74.3587], 12);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
// Re-add Zoom Control on bottom-right for UI cleanliness
L.control.zoom({ position: 'bottomright' }).addTo(map);
let currentMarkers = [];

async function handleUserMessage() {
    const inputField = document.getElementById("user-input");
    const userText = inputField.value;
    if (!userText.trim()) return;

    addMessageToChat("You", userText);
    inputField.value = ""; 

    // Show "Thinking..." animation
    showThinkingBubble();

    // Mock Location (Lahore center)
    const lat = 31.5204;
    const lng = 74.3587;

    const requestPayload = { text: userText, lat: lat, lng: lng };
    
    // Simulate thinking delay for 1.2 seconds
    await new Promise(resolve => setTimeout(resolve, 1200));

    // --> REAL FETCH GOES HERE LATER <--
    const response = await mockQuery(requestPayload); 
    
    // Hide Thinking bubble
    hideThinkingBubble();

    clearMapMarkers();
    
    if (response.matches && response.matches.length > 0) {
        addMessageToChat("Outsy", `Brilliant! I found ${response.matches.length} matches near you. Look at the pins or the details below!`);
        
        response.matches.forEach(event => {
            // Add styled Map Pin
            const marker = L.marker([event.lat, event.lng]).addTo(map)
                .bindPopup(`<b>${event.name}</b><br>🕒 ${event.time}`);
            currentMarkers.push(marker);
            // subtle bounce for marker pop-in
            marker.openPopup();

            // Add new styled Chat Card
            renderEventCard(event);
        });

        // Dynamic center map on the results cluster
        const group = new L.featureGroup(currentMarkers);
        map.fitBounds(group.getBounds().pad(0.1));
    } else {
        addMessageToChat("Outsy", "Sorry, I couldn't find anything matching your request right now. Try searching for 'bowling' or 'games'!");
    }
}

// Allows sending message by pressing 'Enter'
function handleEnter(event) { if (event.key === 'Enter') handleUserMessage(); }

// Clear existing markers from the map
function clearMapMarkers() { currentMarkers.forEach(marker => map.removeLayer(marker)); currentMarkers = []; }

// Helper: Displays 'Thinking...' dot animation
function showThinkingBubble() {
    const messagesDiv = document.getElementById("messages");
    const html = `
        <div class="message-row bot-row" id="thinking-container">
            <div class="message-bubble bot-bubble thinking-bubble">
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
                <div class="thinking-dot"></div>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', html);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function hideThinkingBubble() {
    const thinkingContainer = document.getElementById("thinking-container");
    if (thinkingContainer) thinkingContainer.remove();
}

// Helper: Draws distinct, styled bubbles for User and Bot
function addMessageToChat(sender, text) {
    const messagesDiv = document.getElementById("messages");
    const isUser = sender === "You";
    
    const rowClass = isUser ? "user-row" : "bot-row";
    const bubbleClass = isUser ? "user-bubble" : "bot-bubble";
    
    const html = `
        <div class="message-row ${rowClass}">
            <div class="message-bubble ${bubbleClass}">
                ${text}
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', html);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Helper: Draws complex Event Card with new styled components
function renderEventCard(event) {
    const messagesDiv = document.getElementById("messages");
    const cardHTML = `
        <div class="message-row bot-row">
            <div class="event-card">
                <h4>${event.name}</h4>
                <p><span class="card-icon">🕒</span> Time: ${event.time}</p>
                <p><span class="card-icon">📍</span> Location: ${event.location}</p>
                <p><span class="card-icon">💰</span> Est. Price: ${event.price}</p>
                <button class="wa-btn" onclick="handleBooking('${event.event_id}', '${event.name}')">
                    <svg viewBox="0 0 448 512" width="20" height="20"><path fill="white" d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-30.3 1.8-3.7.9-6.9-.5-9.7-1.4-2.8-12.5-30.1-17.1-41.2-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z"/></svg>
                    Book via WhatsApp
                </button>
            </div>
        </div>
    `;
    messagesDiv.insertAdjacentHTML('beforeend', cardHTML);
    // Smooth scroll is applied in JS for immediate feedback
    messagesDiv.scrollTo({ top: messagesDiv.scrollHeight, behavior: 'smooth' });
}

async function handleBooking(event_id, name) {
    const requestPayload = { event_id: event_id, name: name };
    // --> REAL FETCH GOES HERE LATER <--
    const response = await mockBook(requestPayload);
    window.open(response.wa_link, '_blank');
}