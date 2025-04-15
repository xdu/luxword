document.addEventListener('DOMContentLoaded', function() {
  const cardId = document.getElementById('card-id').value;
  
  // Edit/Save functionality
  const editButton = document.getElementById('edit-button');
  const saveButton = document.getElementById('save-button');
  
  editButton.addEventListener('click', function() {
    // Switch to edit mode
    document.getElementById('translation-display').classList.add('is-hidden');
    document.getElementById('transcript-display').classList.add('is-hidden');
    document.getElementById('audio-url-display').classList.add('is-hidden');
    
    document.getElementById('translation-edit').classList.remove('is-hidden');
    document.getElementById('transcript-edit').classList.remove('is-hidden');
    document.getElementById('audio-url-edit').classList.remove('is-hidden');
    
    editButton.classList.add('is-hidden');
    saveButton.classList.remove('is-hidden');
  });
  
  saveButton.addEventListener('click', function() {
    const audioUrl = document.getElementById('audio-url-input').value;
    const transcript = document.getElementById('transcript-input').value;
    const translation = document.getElementById('translation-input').value;
    
    const formData = new FormData();
    formData.append('audio_url', audioUrl);
    formData.append('transcript', transcript);
    formData.append('translation', translation);
    
    fetch(`/flashcards/${cardId}/update`, {
      method: 'POST',
      body: formData
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        // Update display values
        document.getElementById('translation-display').innerHTML = translation.replace(/\n/g, '<br>');
        document.getElementById('transcript-display').innerHTML = transcript.replace(/\n/g, '<br>');
        document.getElementById('audio-url-display').textContent = audioUrl;
        
        // Switch back to view mode
        document.getElementById('translation-display').classList.remove('is-hidden');
        document.getElementById('transcript-display').classList.remove('is-hidden');
        document.getElementById('audio-url-display').classList.remove('is-hidden');
        
        document.getElementById('translation-edit').classList.add('is-hidden');
        document.getElementById('transcript-edit').classList.add('is-hidden');
        document.getElementById('audio-url-edit').classList.add('is-hidden');
        
        editButton.classList.remove('is-hidden');
        saveButton.classList.add('is-hidden');
      }
    });
  });
  
  // Delete functionality with confirmation modal
  const deleteButton = document.getElementById('delete-button');
  const deleteModal = document.getElementById('delete-modal');
  const confirmDelete = document.getElementById('confirm-delete');
  const cancelDelete = document.getElementById('cancel-delete');
  const closeModal = document.getElementById('close-modal');
  
  deleteButton.addEventListener('click', function() {
    deleteModal.classList.add('is-active');
  });
  
  function closeDeleteModal() {
    deleteModal.classList.remove('is-active');
  }
  
  closeModal.addEventListener('click', closeDeleteModal);
  cancelDelete.addEventListener('click', closeDeleteModal);
  
  confirmDelete.addEventListener('click', function() {
    fetch(`/flashcards/${cardId}/delete`, {
      method: 'POST'
    })
    .then(data => {
      if (data.status === 200) {
        window.location.href = "/flashcards";
      }
    });
  });
});
