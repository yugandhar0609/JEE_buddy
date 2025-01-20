from django.http import JsonResponse
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from .agents.math_agent_1 import MathAgent
import asyncio
import logging
import json
from .models import ChatHistory, UserProfile
import base64
import uuid
from django.db import connections
import os
from django.views.decorators.csrf import csrf_exempt
from django.db.models import F, Q, Count
from django.db.models.expressions import Case, When
from django.db.models.functions import Now, Trunc
from asgiref.sync import sync_to_async
logger = logging.getLogger(__name__)



@api_view(['GET'])
def get_current_profile(request):
    """Get user profile from Supabase profiles table"""
    try:
        # Get the user ID from request headers or query params
        user_id = request.GET.get('user_id') or request.headers.get('X-User-Id')
        
        if not user_id:
            return Response({
                'error': 'User ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Query the profiles table
        with connections['default'].cursor() as cursor:
            cursor.execute("""
                SELECT uuid, name, email, current_session_id, created_at, updated_at
                FROM profiles 
                WHERE uuid = %s
            """, [user_id])
            
            row = cursor.fetchone()
            
            if row:
                profile_data = {
                    'uuid': row[0],
                    'name': row[1],
                    'email': row[2],
                    'current_session_id': row[3],
                    'created_at': row[4],
                    'updated_at': row[5]
                }
                
                # If no session ID exists, generate one and update
                if not profile_data['current_session_id']:
                    new_session_id = f"session_{uuid.uuid4().hex[:8]}"
                    cursor.execute("""
                        UPDATE profiles 
                        SET current_session_id = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE uuid = %s
                    """, [new_session_id, user_id])
                    profile_data['current_session_id'] = new_session_id
                
                return Response(profile_data)
            
            return Response({
                'error': 'Profile not found'
            }, status=status.HTTP_404_NOT_FOUND)
            
    except Exception as e:
        logger.error(f"Error in get_current_profile: {str(e)}", exc_info=True)
        return Response({
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@csrf_exempt
async def solve_math_problem(request):
    try:
        # Parse request data
        if request.method != 'POST':
            return JsonResponse({
                'error': 'Method not allowed'
            }, status=405)
            
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Invalid JSON data'
            }, status=400)
            
        # Extract data from request
        question = data.get('question')
        if not question:
            return JsonResponse({
                'error': 'Question is required'
            }, status=400)
        
        # Handle context data
        context_data = data.get('context', {})
        
        # Get user and session info
        user_id = context_data.get('user_id')
        session_id = context_data.get('session_id')
        history_limit = context_data.get('history_limit', 100)

        # Get chat history for the specific user and session
        chat_history = []
        if user_id and session_id:
            try:
                # Get recent chat history
                chat_history = await sync_to_async(ChatHistory.get_recent_history)(
                    user_id=user_id,
                    session_id=session_id,
                    limit=history_limit
                )
            except Exception as e:
                logger.error(f"Error fetching chat history: {str(e)}")
        
        # Create the context dictionary
        context = {
            'user_id': user_id,
            'session_id': session_id,
            'chat_history': chat_history,
            'history_limit': history_limit,
            'image': None,  # Handle image if needed
            'interaction_type': context_data.get('interaction_type', 'solve'),
            'pinnedText': context_data.get('pinnedText', ''),
            'selectedText': context_data.get('selectedText', ''),
            'subject': context_data.get('subject', ''),
            'topic': context_data.get('topic', '')
        }

        # Initialize math agent using the create() factory method
        agent = await MathAgent.create()
        
        # Call solve method directly since we're in an async view
        solution = await agent.solve(question, context)
        
        if not solution or not solution.get('solution'):
            return JsonResponse({
                'error': 'No solution generated',
                'details': 'The AI agent failed to generate a response.'
            }, status=500)

        # Save the interaction to chat history
        if user_id and session_id:
            try:
                await sync_to_async(ChatHistory.add_interaction)(
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    response=solution['solution'],
                    context={
                        'subject': context.get('subject'),
                        'topic': context.get('topic'),
                        'interaction_type': context.get('interaction_type'),
                        'pinned_text': context.get('pinnedText'),
                    }
                )
            except Exception as e:
                logger.error(f"Error saving chat history: {str(e)}")

        # Get updated chat history
        updated_chat_history = []
        if user_id and session_id:
            try:
                updated_chat_history = await sync_to_async(ChatHistory.get_recent_history)(
                    user_id=user_id,
                    session_id=session_id,
                    limit=history_limit
                )
            except Exception as e:
                logger.error(f"Error fetching updated chat history: {str(e)}")

        # Prepare response data
        response_data = {
            'solution': solution['solution'],
            'context': {
                'current_question': question,
                'response': solution['solution'],
                'user_id': user_id,
                'session_id': session_id,
                'subject': context.get('subject'),
                'topic': context.get('topic'),
                'chat_history': updated_chat_history
            }
        }
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error in solve_math_problem: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': str(e),
            'details': 'An unexpected error occurred while processing your request.'
        }, status=500)

