import json
import random
import sys
import time
import copy
import math

import http.client
from collections import namedtuple


SERVER = '172.16.0.2'
TOKEN = 'b1985422-b8fe-40d3-8c54-cb1d50fc0af5'


Cursor = namedtuple('Cursor', ['x', 'y'])

class OutOfBoardError(Exception):
    pass


def get_cell(board, cursor):
    if cursor.x < 0 or cursor.y < 0:
        raise OutOfBoardError

    try:
        return board[cursor.y][cursor.x]
    except IndexError:
        raise OutOfBoardError

def move_cursor(cursor, direction):
    if direction == 'left':
        return Cursor(cursor.x - 1, cursor.y)
    if direction == 'right':
        return Cursor(cursor.x + 1, cursor.y)
    if direction == 'up':
        return Cursor(cursor.x, cursor.y - 1)
    if direction == 'down':
        return Cursor(cursor.y, cursor.y + 1)


def explore(points, moves, board, cursor, direction):
    new_cursor = move_cursor(cursor, direction)
    try:
        is_consumed = get_cell(board, new_cursor).get('consumed', False)
        if not is_consumed:
            # consume new cell
            got_points, new_direction = consume(board, new_cursor)
            points += got_points
        else:
            # cell is consumed
            new_direction = direction
        moves += 1
        return explore(points, moves, board, new_cursor, new_direction)
    except OutOfBoardError:
        return points, moves

def consume(board, cursor):
    cell = get_cell(board, cursor)
    cell.update({'consumed': True})
    return cell['points'], cell['direction']

def decide_on_next_move(results, strategy):
    def normalize(points, max_points, moves, max_moves):
        POINTS_WEIGHT = 0.55
        MOVES_WEIGHT = 1 - POINTS_WEIGHT

        if not max_points:
            points_scaled = 0
        else:
            points_scaled = points / float(max_points)
        
        if not max_moves:
            moves_scaled = 0
        else:
            moves_scaled = moves / float(max_moves)

        return points_scaled * POINTS_WEIGHT + moves_scaled * MOVES_WEIGHT

    def _max_points_strategy(results):
        results = sorted(results, 
            key=lambda result: result[1])[::-1]
        return results[0]

    def _max_moves_strategy(results):
        results = sorted(results, 
            key=lambda result: result[2])[::-1]
        return results[0]

    def _max_points_max_moves(results):
        sorted_max_points = sorted(results, 
            key=lambda result: result[1])[::-1]
        top_max_points = sorted_max_points[:5]
        return _max_moves_strategy(top_max_points)

    def _max_points_max_extra_moves(results):
        sorted_max_extra_moves = sorted(results, 
            key=lambda result: result[3])[::-1]

        extra_moves = sorted_max_extra_moves[0][3]
        if extra_moves:
            return sorted_max_extra_moves[0]

        return _max_points_strategy(results)

    def _normalized(results):
        # init_cursor, points + extra_points, moves, extra_moves
        max_points = max([result[1] for result in results])
        max_extra_moves = max([result[3] for result in results])
        normalized_weights = [
            normalize(result[1], max_points, result[3], max_extra_moves)
            for result in results
        ]
        print("[d] normalized weights {}".format(normalized_weights))
        max_weight = max(normalized_weights)
        candidate_idx = normalized_weights.index(max_weight)
        return results[candidate_idx]


    strategies = {
        "max_points": _max_points_strategy,
        "max_moves": _max_moves_strategy,
        "max_points_max_moves": _max_points_max_moves, 
        "max_points_max_extra_moves": _max_points_max_extra_moves,
        "normalized": _normalized,
    }

    strategy_func = strategies[strategy]
    cursor, points, moves, extra_moves = strategy_func(results)
    
    print("[i] using {} strategy, best next choice is x={}, y={}, "
          "which gives {} points in {} moves".format(
            strategy, cursor.x, cursor.y, points, moves))

    return cursor

def solve(task_board, strategy, current_score):
    results = []
    board_x_size = len(task_board)
    board_y_size = len(task_board[0])
    print("[i] brute force started, current task board "
          "size is {}x{}".format(board_x_size, board_y_size))

    def _get_possible_extra_moves(chain_length, total_score):
        threshold = math.floor(total_score / (5 * board_x_size * board_x_size)) + board_x_size - 1
        if chain_length >= threshold:
            return chain_length - threshold
        return 0

    for x in range(board_x_size):
        for y in range(board_y_size):
            board_to_explore = copy.deepcopy(task_board)
            init_cursor = Cursor(x, y)
            init_points, init_direction = consume(board_to_explore, init_cursor)
            points, moves = explore(init_points, 1, board_to_explore, 
                                    init_cursor, init_direction)

            
            rows_consumed = 0
            for row in board_to_explore:
                row_consumed = all([cell.get('consumed', False) for cell in row])
                if row_consumed:
                    rows_consumed += 1

            cols_consumed = 0
            for col_idx in range(board_x_size):
                col_consumed = True
                for row in board_to_explore:
                    cell_consumed = row[col_idx].get('consumed', False)
                    if not cell_consumed:
                        col_consumed = False
                if col_consumed:
                    cols_consumed += 1

            extra_points = (rows_consumed + cols_consumed) * board_x_size * 10
            points = points + extra_points
            extra_moves = _get_possible_extra_moves(
                moves, current_score + points
            )

            results.append([init_cursor, points, moves, extra_moves])

            del board_to_explore
            print(" - x={}, y={} gives {} points (extra points {}) "
                  "in {} moves (extra moves {})".format(init_cursor.x, init_cursor.y, 
                                        points + extra_points, extra_points, moves, extra_moves))
    
    return decide_on_next_move(results, strategy)


def do_server_play(token, game, strategy):    
    client = http.client.HTTPConnection(SERVER, 8080)
    client.connect()

    # block until the game starts
    client.request('GET', '/games/{}/board?token={}'.format(game, token))

    i = 0
    response = client.getresponse()
    
    while response.status == 200:
        data = json.loads(response.read().decode())

        print("[***] step {}, current score {}, moves we have left {}".format(
            i, data["score"], data["moves"]))

        next_cursor = solve(
            data["board"], strategy, data["score"]
        )

        time.sleep(0.2)

        # make move and wait for a new round
        client.request(
            'POST', '/games/{}/board?token={}'.format(game, token),
            json.dumps({
                'x': next_cursor.x,
                'y': next_cursor.y,
            })
        )

        response = client.getresponse()
        i += 1
    else:
        print("[i] response done, got server code {}".format(response.status))

if __name__ == '__main__':
    # game: 0 (development mode), 1 (duel), 2 (contest)
    print("[i] starting the game")
    do_server_play(token=TOKEN, game=2, strategy="normalized")
    print("[i] all done")
