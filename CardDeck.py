import random

class CardDeck:
    def __init__(self):
        self.cards = []
        self.remaining_cards = []
            
        for suit in ['C', 'H', 'D', 'S']:
            for num in ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']:
                self.cards.append(num+suit)

    def shuffle_deck(self):
        # shuffles cards in place
        random.shuffle(self.cards)

    # returns specified number of hands
    def deal_cards(self, num):
        self.shuffle_deck()

        hands = []
        ind = 0

        for i in range(num):
            hands.append(self.cards[ind:ind+4])
            ind += 4

        self.remaining_cards = self.cards[ind:]
        return hands