/**
 * GameStore Catalog API Client
 *
 * A simple JavaScript client to interact with the GameStore Catalog API.
 */
class GameCatalogAPI {
  /**
   * @param {string} [baseUrl] - The base URL of the API. Defaults to current window origin.
   */
  constructor(baseUrl = '') {
      this.baseUrl = baseUrl || window.location.origin;
      this.defaultSite = 'ovagames'; // Default site if not specified
  }

  /**
   * Sets the default site for subsequent API calls.
   * @param {string} siteId - The ID of the site to set as default.
   */
  setDefaultSite(siteId) {
      this.defaultSite = siteId;
  }

  /**
   * Performs a fetch request to the API.
   * @param {string} endpoint - The API endpoint to call.
   * @param {object} [params] - Query parameters for the request.
   * @returns {Promise<object>} - A promise that resolves with the JSON response.
   * @private
   */
  async _request(endpoint, params = {}) {
      const url = new URL(`${this.baseUrl}/api${endpoint}`);
      
      // Ensure 'site' parameter is included if not already present, using defaultSite
      if (!params.site && endpoint !== '/sites') {
          params.site = this.defaultSite;
      }

      Object.keys(params).forEach(key => {
          if (params[key] !== undefined && params[key] !== null) {
              url.searchParams.append(key, params[key]);
          }
      });

      try {
          const response = await fetch(url.toString());
          if (!response.ok) {
              let errorData;
              try {
                  errorData = await response.json();
              } catch (e) {
                  errorData = { message: response.statusText };
              }
              throw new Error(errorData.message || `HTTP error! status: ${response.status}`);
          }
          return await response.json();
      } catch (error) {
          console.error('API Request Error:', error);
          throw error;
      }
  }

  /**
   * Gets the list of available sites.
   * @returns {Promise<object>}
   */
  async getSites() {
      return this._request('/sites');
  }

  /**
   * Gets a list of games.
   * @param {object} [options] - Options for the request.
   * @param {string} [options.site] - The site ID. Defaults to `this.defaultSite`.
   * @param {number} [options.page=1] - Page number.
   * @param {string} [options.category] - Category slug.
   * @returns {Promise<object>}
   */
  async getGames({ site, page = 1, category } = {}) {
      return this._request('/games', { site: site || this.defaultSite, page, category });
  }

  /**
   * Gets detailed information for a specific game.
   * @param {string} gameUrl - The full URL of the game page.
   * @param {string} [site] - The site ID. Defaults to `this.defaultSite`.
   * @returns {Promise<object>}
   */
  async getGameDetails(gameUrl, site) {
      if (!gameUrl) {
          return Promise.reject(new Error("Game URL is required."));
      }
      return this._request('/game', { url: gameUrl, site: site || this.defaultSite });
  }

  /**
   * Searches for games.
   * @param {string} query - The search query.
   * @param {string} [site] - The site ID. Defaults to `this.defaultSite`.
   * @returns {Promise<object>}
   */
  async searchGames(query, site) {
      if (!query) {
          return Promise.reject(new Error("Search query is required."));
      }
      return this._request('/search', { q: query, site: site || this.defaultSite });
  }
}

// Example Usage (can be commented out or removed)
/*
document.addEventListener('DOMContentLoaded', async () => {
  const api = new GameCatalogAPI();

  try {
      // Set default site (optional, defaults to 'ovagames' in client)
      // const sitesData = await api.getSites();
      // if (sitesData.sites && sitesData.sites.length > 0) {
      //     api.setDefaultSite(sitesData.sites[0].id); // Set to the first available site
      //     console.log(`Default site set to: ${sitesData.sites[0].id}`);
      // }
      
      console.log('Fetching sites...');
      const sites = await api.getSites();
      console.log('Available sites:', sites);

      if (sites.sites && sites.sites.length > 0) {
          const firstSiteId = sites.sites[0].id;
          api.setDefaultSite(firstSiteId); // Important for subsequent calls if site isn't specified

          console.log(`\nFetching games from ${firstSiteId}...`);
          const games = await api.getGames({ site: firstSiteId, page: 1 });
          console.log('Games:', games);

          if (games.games && games.games.length > 0) {
              const firstGameUrl = games.games[0].url;
              console.log(`\nFetching details for game: ${firstGameUrl}`);
              const gameDetails = await api.getGameDetails(firstGameUrl, firstSiteId);
              console.log('Game Details:', gameDetails);
          }

          console.log(`\nSearching for "action" games on ${firstSiteId}...`);
          const searchResults = await api.searchGames('action', firstSiteId);
          console.log('Search Results:', searchResults);
      }

  } catch (error) {
      console.error('API Test Error:', error);
  }
});
*/