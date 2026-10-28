package com.dsefa.flir;

import android.content.Context;
import android.graphics.*;
import android.view.*;
import java.util.*;

public final class ThermalView extends View {
    public final Thermal.Settings settings=new Thermal.Settings();
    public boolean showMaximumGraph=true,trackMaximum=true,trackMinimum=false;
    private final Thermal.Renderer renderer=new Thermal.Renderer();
    private final ScaleGestureDetector pinch;private float zoom=1;private boolean pinching;
    private Bitmap bitmap;private final Paint paint=new Paint(3);
    private final Matrix transform=new Matrix();
    private final Matrix inverse=new Matrix();
    private final OverlayModel maximum=new OverlayModel();
    private double[] measurementTemps;private int bottomInset;
    private int[] raw;private double[] temps;
    private long timestamp;private int cursor=-1;
    private final List<Integer> points=new ArrayList<>();
    public interface PointListener{void changed(List<Integer> points);}
    public PointListener listener;
    public ThermalView(Context c){super(c);setBackgroundColor(Color.rgb(5,6,9));pinch=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){
        public boolean onScaleBegin(ScaleGestureDetector d){pinching=true;return true;}
        public boolean onScale(ScaleGestureDetector d){zoom=Math.max(1,Math.min(8,zoom*d.getScaleFactor()));invalidate();return true;}});}
    public void frame(int[] r,long t){raw=r;timestamp=t;refresh();}
    public void result(FramePipeline.Result r){raw=r.raw;timestamp=r.timestamp;temps=r.temperatures;measurementTemps=temps;
        if(r.colors!=null){if(bitmap==null||bitmap.getWidth()!=160||bitmap.getHeight()!=120)bitmap=Bitmap.createBitmap(160,120,Bitmap.Config.ARGB_8888);bitmap.setPixels(r.colors,0,160,0,0,160,120);}invalidate();}
    public void savedImage(byte[] jpeg,long stamp){BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeByteArray(jpeg,0,jpeg.length,bounds);
        if(bounds.outWidth!=160||bounds.outHeight!=120)throw new IllegalArgumentException("Expected a 160 × 120 image clip");Bitmap decoded=BitmapFactory.decodeByteArray(jpeg,0,jpeg.length);if(decoded==null)throw new IllegalArgumentException("Invalid saved JPEG");bitmap=decoded;timestamp=stamp;raw=null;temps=null;measurementTemps=null;maximum.clear();invalidate();}
    public int[] raw(){return raw;}
    public double[] temperatures(){return temps;}
    public List<Integer> points(){return new ArrayList<>(points);}
    public void safeBottom(int pixels){bottomInset=pixels;invalidate();}
    public void measure(double[] values,long stamp){measurementTemps=values;maximum.add(stamp,values);invalidate();}
    public void resetTimeline(){maximum.clear();measurementTemps=null;invalidate();}
    public void clearPoints(){points.clear();cursor=-1;if(listener!=null)listener.changed(points());invalidate();}
    public void resetMeasurements(){clearPoints();resetTimeline();}
    public void resetZoom(){zoom=1;invalidate();}
    public void resetDisplayModel(){renderer.reset();refresh();}
    public String displayInfo(){return renderer.description;}
    public long timestamp(){return timestamp;}
    public void refresh(){if(raw==null){invalidate();return;}temps=Thermal.temperatures(raw,settings);measurementTemps=temps;
        int[] pixels=renderer.render(temps,settings,timestamp);
        if(bitmap==null)bitmap=Bitmap.createBitmap(160,120,Bitmap.Config.ARGB_8888);
        bitmap.setPixels(pixels,0,160,0,0,160,120);invalidate();}
    public double sample(int i){return Thermal.sample(measurementTemps,i,settings.average);}
    public static double average(double[] values,int i){if(values==null||i<0||i>=values.length)return Double.NaN;
        int x=i%160,y=i/160;double sum=0;int count=0;
        for(int yy=Math.max(0,y-1);yy<=Math.min(119,y+1);yy++)for(int xx=Math.max(0,x-1);xx<=Math.min(159,x+1);xx++){
            double v=values[yy*160+xx];if(Double.isFinite(v)){sum+=v;count++;}}
        return count>0?sum/count:Double.NaN;
    }
    private float density(){return getResources().getDisplayMetrics().density;}
    private void matrix(){
        boolean sideways=settings.rotation%180!=0;
        float availableH=Math.max(1,getHeight());
        float scale=Math.min(getWidth()/(sideways?120f:160f),availableH/(sideways?160f:120f));
        transform.reset();transform.postTranslate(-80,-60);
        transform.postScale(settings.mirror?-1:1,1);transform.postRotate(settings.rotation);
        transform.postScale(scale*zoom,scale*zoom);transform.postTranslate(getWidth()/2f,availableH/2f);
        transform.invert(inverse);
    }
    protected void onDraw(Canvas canvas){super.onDraw(canvas);paint.setColor(0xffb5bbc4);paint.setTextSize(14*density());
        if(bitmap==null){canvas.drawText("Connect FLIR ONE Gen 2 through USB OTG",12*density(),getHeight()/2f,paint);return;}
        matrix();paint.setFilterBitmap(settings.smooth);canvas.drawBitmap(bitmap,transform,paint);
        if(measurementTemps!=null)for(int n=0;n<points.size();n++)marker(canvas,points.get(n),"P"+(n+1),0xffffffff);
        if(measurementTemps!=null){int hot=-1,cold=-1;for(int i=0;i<measurementTemps.length;i++)if(Double.isFinite(measurementTemps[i])){if(hot<0||measurementTemps[i]>measurementTemps[hot])hot=i;if(cold<0||measurementTemps[i]<measurementTemps[cold])cold=i;}
            if(trackMaximum&&hot>=0)marker(canvas,hot,"MAX "+Thermal.formatTemperature(measurementTemps[hot],settings),0xffffffff);
            if(trackMinimum&&cold>=0)marker(canvas,cold,"MIN "+Thermal.formatTemperature(measurementTemps[cold],settings),0xffffffff);}
        float rowHeight=18*density(),bottom=getHeight()-bottomInset-18*density();
        if(measurementTemps!=null)for(int n=0;n<points.size();n++)text(canvas,"P"+(n+1)+"  ·  "+Thermal.formatTemperature(sample(points.get(n)),settings),18*density(),bottom-(points.size()-1-n)*rowHeight,11*density());
        if(showMaximumGraph)drawMaximum(canvas,bottom-points.size()*rowHeight-16*density());
    }
    private void marker(Canvas c,int i,String label,int color){float[] p={i%160+.5f,i/160+.5f};transform.mapPoints(p);
        float d=density();color=contrast(p[0]-5*d,p[1]+5*d,10*d,10*d);
        paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(3*d);paint.setColor(color==Color.WHITE?Color.BLACK:Color.WHITE);
        c.drawCircle(p[0],p[1],5*d,paint);paint.setStrokeWidth(1.2f*d);paint.setColor(color);c.drawCircle(p[0],p[1],5*d,paint);
        paint.setStyle(Paint.Style.FILL);text(c,label,Math.max(8*d,Math.min(p[0]+9*d,getWidth()-35*d)),Math.max(16*d,p[1]-8*d),10*d);}
    private int pixel(float x,float y){float[] p={x,y};inverse.mapPoints(p);int xx=(int)Math.floor(p[0]),yy=(int)Math.floor(p[1]);
        return bitmap!=null&&xx>=0&&xx<160&&yy>=0&&yy<120?bitmap.getPixel(xx,yy):0xff050609;}
    private int contrast(float x,float y,float width,float height){int[] colors=new int[15];int n=0;
        for(int yy=0;yy<3;yy++)for(int xx=0;xx<5;xx++)colors[n++]=pixel(x+width*xx/4,y-height+height*yy/2);
        return OverlayModel.textColor(colors);}
    private void text(Canvas c,String label,float x,float y,float size){paint.setTextSize(size);paint.setTextAlign(Paint.Align.LEFT);
        int color=contrast(x,y,paint.measureText(label),size);paint.setStyle(Paint.Style.STROKE);paint.setStrokeWidth(1.5f*density());paint.setColor(color==Color.WHITE?Color.BLACK:Color.WHITE);
        c.drawText(label,x,y,paint);paint.setStyle(Paint.Style.FILL);paint.setColor(color);c.drawText(label,x,y,paint);}
    private void drawMaximum(Canvas c,float bottom){List<OverlayModel.Sample> samples=maximum.samples();if(samples.size()<2)return;
        float d=density(),left=50*d,right=getWidth()-22*d,top=bottom-58*d;if(top<80*d||right<=left)return;
        double low=Double.POSITIVE_INFINITY,high=Double.NEGATIVE_INFINITY;
        for(OverlayModel.Sample s:samples){low=Math.min(low,s.value);high=Math.max(high,s.value);}
        double actualLow=low,actualHigh=high,span=Math.max(.5,high-low),center=(high+low)/2;low=center-span*.6;high=center+span*.6;
        long end=samples.get(samples.size()-1).stamp;float lastX=0,lastY=0;boolean first=true;
        line(c,left,top-4*d,left,bottom);line(c,left,bottom,right+4*d,bottom);
        line(c,left,top-4*d,left-3*d,top+2*d);line(c,left,top-4*d,left+3*d,top+2*d);
        line(c,right+4*d,bottom,right-2*d,bottom-3*d);line(c,right+4*d,bottom,right-2*d,bottom+3*d);
        text(c,String.format(Locale.US,"%.1f°",Thermal.displayTemperature(actualHigh,settings)),8*d,top+7*d,9*d);
        text(c,String.format(Locale.US,"%.1f°",Thermal.displayTemperature(actualLow,settings)),8*d,bottom,9*d);
        text(c,"−30s",left,bottom+12*d,8*d);text(c,"now",right-20*d,bottom+12*d,8*d);
        for(OverlayModel.Sample s:samples){float x=left+(right-left)*(s.stamp-(end-OverlayModel.WINDOW))/(float)OverlayModel.WINDOW;
            float y=bottom-(float)((s.value-low)/(high-low))*(bottom-top);
            if(!first){int color=OverlayModel.textColor(new int[]{pixel(lastX,lastY),pixel(x,y),pixel((x+lastX)/2,(y+lastY)/2)});
                paint.setStyle(Paint.Style.STROKE);paint.setStrokeCap(Paint.Cap.ROUND);paint.setColor(color==Color.WHITE?Color.BLACK:Color.WHITE);
                paint.setStrokeWidth(3*d);c.drawLine(lastX,lastY,x,y,paint);paint.setColor(color);paint.setStrokeWidth(1.2f*d);c.drawLine(lastX,lastY,x,y,paint);}
            lastX=x;lastY=y;first=false;}
        paint.setStyle(Paint.Style.FILL);}
    private void line(Canvas c,float x1,float y1,float x2,float y2){int color=OverlayModel.textColor(new int[]{pixel(x1,y1),pixel(x2,y2)});
        paint.setStyle(Paint.Style.STROKE);paint.setColor(color==Color.WHITE?Color.BLACK:Color.WHITE);paint.setStrokeWidth(2*density());c.drawLine(x1,y1,x2,y2,paint);
        paint.setColor(color);paint.setStrokeWidth(.65f*density());c.drawLine(x1,y1,x2,y2,paint);paint.setStyle(Paint.Style.FILL);}
    public boolean onTouchEvent(MotionEvent event){if(bitmap==null)return true;pinch.onTouchEvent(event);
        if(event.getActionMasked()==MotionEvent.ACTION_DOWN)pinching=false;
        if(pinching||event.getPointerCount()>1){invalidate();return true;}
        float[] p={event.getX(),event.getY()};Matrix inverse=new Matrix();matrix();if(!transform.invert(inverse))return true;inverse.mapPoints(p);
        if(p[0]<0||p[0]>=160||p[1]<0||p[1]>=120)return true;
        cursor=(int)p[1]*160+(int)p[0];
        if(event.getAction()==MotionEvent.ACTION_UP&&measurementTemps!=null){int near=-1;
            for(int i=0;i<points.size();i++)if(Math.hypot(points.get(i)%160-p[0],points.get(i)/160-p[1])<5){near=i;break;}
            if(near>=0)points.remove(near);else if(points.size()<8)points.add(cursor);
            if(listener!=null)listener.changed(points());performClick();}
        invalidate();return true;}
    public boolean performClick(){super.performClick();return true;}
    public Bitmap snapshot(){Bitmap b=Bitmap.createBitmap(Math.max(1,getWidth()),Math.max(1,getHeight()),Bitmap.Config.ARGB_8888);draw(new Canvas(b));return b;}
}
