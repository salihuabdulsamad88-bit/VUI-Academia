document.addEventListener('DOMContentLoaded', () => {
    
    // Bookmark Toggle Logic
    const bookmarkBtns = document.querySelectorAll('.bookmark-btn');
    
    bookmarkBtns.forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            const docId = btn.getAttribute('data-doc-id');
            
            try {
                const response = await fetch(`/bookmark/${docId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });
                
                if (response.ok) {
                    const data = await response.json();
                    if (data.status === 'added') {
                        btn.classList.add('active');
                        // Optional: Add a small micro-animation or toast notification here
                    } else if (data.status === 'removed') {
                        btn.classList.remove('active');
                    }
                } else {
                    console.error("Failed to toggle bookmark");
                }
            } catch (error) {
                console.error("Error:", error);
            }
        });
    });

    // Auto-dismiss flash messages after 5 seconds
    const flashMessages = document.querySelectorAll('.flash');
    if (flashMessages.length > 0) {
        setTimeout(() => {
            flashMessages.forEach(msg => {
                msg.style.opacity = '0';
                msg.style.transform = 'translateX(100%)';
                msg.style.transition = 'all 0.3s ease-in';
                setTimeout(() => msg.remove(), 300);
            });
        }, 5000);
    }
    
    // Theme Toggle Logic
    const themeToggleBtn = document.getElementById('theme-toggle');
    const themeIcon = document.getElementById('theme-icon');
    
    // Check saved theme
    const savedTheme = localStorage.getItem('vui-theme');
    if (savedTheme === 'light') {
        document.body.classList.add('light-mode');
        themeIcon.setAttribute('data-feather', 'sun');
    }
    
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', () => {
            document.body.classList.toggle('light-mode');
            const isLight = document.body.classList.contains('light-mode');
            
            localStorage.setItem('vui-theme', isLight ? 'light' : 'dark');
            
            // Update Icon
            themeIcon.setAttribute('data-feather', isLight ? 'sun' : 'moon');
            feather.replace(); // Re-render the icon
        });
    }

    // Add stagger classes to document cards dynamically
    const docCards = document.querySelectorAll('.doc-card');
    docCards.forEach((card, index) => {
        card.classList.add('fade-in');
        card.style.animationDelay = `${index * 0.1}s`;
    });
});
